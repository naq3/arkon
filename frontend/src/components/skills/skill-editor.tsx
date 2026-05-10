"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import * as diff from "diff";
import { api, apiUpload } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkFrontmatter from "remark-frontmatter";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type SkillFile = {
  path: string;
  size: number;
  is_text: boolean;
};

type TreeNode = {
  name: string;
  path: string;
  type: "file" | "folder";
  children?: TreeNode[];
  is_text?: boolean;
};

type SkillEditorProps = {
  contributionId: string;
  onSubmitted?: () => void;
  onStatusChange?: () => void;
  mode?: "edit" | "review";
};

export function SkillEditor({ contributionId, onSubmitted, onStatusChange, mode = "review" }: SkillEditorProps) {
  const { user, hasPermission } = useAuth();
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [lastSavedContent, setLastSavedContent] = useState<string>("");
  const [contentLoading, setContentLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set([""]));
  const [isEditMode, setIsEditMode] = useState(true);
  const [diffMode, setDiffMode] = useState(false);
  const [originalContent, setOriginalContent] = useState<string | null>(null);
  const [contribution, setContribution] = useState<any>(null);
  const [uploadTargetPath, setUploadTargetPath] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [diffStatus, setDiffStatus] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const loadDiffStatus = useCallback(async () => {
    try {
      const data = await api<Record<string, string>>(`/api/skill-contributions/${contributionId}/diff-status`);
      setDiffStatus(data);
    } catch (err) {
      console.error("Failed to load diff status:", err);
    }
  }, [contributionId]);

  const buildTree = (files: SkillFile[]): TreeNode[] => {
    const root: TreeNode[] = [];
    files.forEach((file) => {
      const parts = file.path.split("/").filter(p => p !== "");
      let currentLevel = root;
      let currentPath = "";

      parts.forEach((part, index) => {
        currentPath = currentPath ? `${currentPath}/${part}` : part;
        const isLast = index === parts.length - 1;

        let node = currentLevel.find((n) => n.name === part && n.type === (isLast ? "file" : "folder"));
        if (!node) {
          node = {
            name: part,
            path: currentPath,
            type: isLast ? "file" : "folder",
            is_text: isLast ? file.is_text : undefined,
            children: isLast ? undefined : [],
          };
          currentLevel.push(node);
        }
        if (!isLast && node.children) {
          currentLevel = node.children;
        }
      });
    });

    const sortNodes = (nodes: TreeNode[]) => {
      nodes.sort((a, b) => {
        if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      nodes.forEach((n) => {
        if (n.children) sortNodes(n.children);
      });
    };

    sortNodes(root);
    return root;
  };

  const getNodeStatus = (node: TreeNode): string | null => {
    if (node.type === "file") {
      return diffStatus[node.path] || null;
    }

    // Folder: check all descendants
    const getDescendantStatuses = (n: TreeNode): string[] => {
      let statuses: string[] = [];
      if (n.children) {
        n.children.forEach(child => {
          if (child.type === "file") {
            const s = diffStatus[child.path];
            if (s) statuses.push(s);
            else statuses.push("unchanged"); // Track unchanged files too
          } else {
            statuses = [...statuses, ...getDescendantStatuses(child)];
          }
        });
      }
      return statuses;
    };

    const childStatuses = getDescendantStatuses(node);
    const uniqueStatuses = Array.from(new Set(childStatuses)).filter(s => s !== "unchanged");

    if (uniqueStatuses.length === 0) return null;
    if (uniqueStatuses.length === 1) {
      // If all files in folder have same status, show that status
      const allFilesCount = childStatuses.length;
      const statusFilesCount = childStatuses.filter(s => s === uniqueStatuses[0]).length;
      if (allFilesCount === statusFilesCount) return uniqueStatuses[0];
    }

    return "M"; // Mixed changes or some unchanged files
  };

  const StatusBadge = ({ status }: { status: string | null }) => {
    if (!status || mode !== "review") return null;

    const colors = {
      M: "bg-amber-100 text-amber-700 border-amber-200",
      A: "bg-emerald-100 text-emerald-700 border-emerald-200",
      D: "bg-destructive/10 text-destructive border-destructive/20",
    };

    const labels = {
      M: "Modified",
      A: "Added",
      D: "Deleted",
    };

    return (
      <span
        title={labels[status as keyof typeof labels]}
        className={cn(
          "flex items-center justify-center w-4 h-4 text-[9px] font-bold rounded-full border shadow-sm select-none shrink-0 cursor-help",
          colors[status as keyof typeof colors]
        )}
      >
        {status}
      </span>
    );
  };

  const displayFiles = useMemo(() => {
    // In edit mode, we only want to see files that actually exist in the contribution
    if (mode === "edit") return files;

    // In review mode, we want to see deleted files too (so we can show the diff)
    const result = [...files];
    Object.entries(diffStatus).forEach(([path, status]) => {
      if (status === "D") {
        if (!result.some(f => f.path === path)) {
          result.push({ path, size: 0, is_text: true });
        }
      }
    });
    return result;
  }, [files, diffStatus, mode]);

  const fileTree = useMemo(() => buildTree(displayFiles), [displayFiles]);

  const rootFolderName = useMemo(() => {
    if (displayFiles.length === 0) return null;
    const firstPath = displayFiles[0].path;
    return firstPath.split("/")[0];
  }, [displayFiles]);


    const loadFiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api<SkillFile[]>(`/api/skill-contributions/${contributionId}/files`);
      setFiles(data);
      if (!selectedPath && data.length > 0) {
        const readme = data.find(f => f.path.toLowerCase().endsWith("skill.md"));
        if (readme) setSelectedPath(readme.path);
        else setSelectedPath(data[0].path);
      }
    } catch (err: any) {
      console.error("Failed to load contribution files:", err);
      // Kiểm tra lỗi 400 từ Backend
      if (err.status === 400) {
        window.location.reload();
      } else {
        setError("An error occurred while loading files.");
      }
    } finally {
      setLoading(false);
      loadDiffStatus();
    }
  }, [contributionId, selectedPath, loadDiffStatus]);


  const loadContent = useCallback(async (path: string) => {
    setContentLoading(true);
    setSaveStatus("idle");
    setOriginalContent(null);

    // If file is marked as deleted, don't even try to fetch its content
    if (diffStatus[path] === "D") {
      setContent("");
      setLastSavedContent("");
    } else {
      try {
        const data = await api<{ content: string }>(`/api/skill-contributions/${contributionId}/files/content?path=${encodeURIComponent(path)}`);
        setContent(data.content);
        setLastSavedContent(data.content);
      } catch (err) {
        console.warn(`[Editor] Failed to fetch content for ${path}:`, err);
        setContent("");
        setLastSavedContent("");
      }
    }

    try {
      // If we have contribution metadata, try to load original content for diff (only if pending or reviewer)
      const isPending = contribution?.status === "pending";
      const isAdmin = user?.role === "admin";
      const canReview = hasPermission("skill:contribution:review");


      if (contribution && (isPending || isAdmin || canReview) && contribution.skill_id) {

        // Normalize path: strip root folder name if it matches the start of the path
        let normalizedPath = path;
        if (rootFolderName && path.startsWith(rootFolderName + "/")) {
          normalizedPath = path.replace(rootFolderName + "/", "");
        }


        try {
          // Try original path first
          let origUrl = `/api/skills/${contribution.skill_id}/files/content?path=${encodeURIComponent(normalizedPath)}`;
          if (contribution.base_version) {
            origUrl += `&version=${contribution.base_version}`;
          }

          const origData = await api<{ content: string }>(origUrl);
          setOriginalContent(origData.content);
        } catch (e) {
          // If normalized path failed, try the raw path as fallback
          try {
            let rawUrl = `/api/skills/${contribution.skill_id}/files/content?path=${encodeURIComponent(path)}`;
            if (contribution.base_version) {
              rawUrl += `&version=${contribution.base_version}`;
            }

            const rawData = await api<{ content: string }>(rawUrl);
            setOriginalContent(rawData.content);
          } catch (e2) {
            // If both fail, it's likely a new file. Set to null to indicate no original version.
            setOriginalContent(null);
          }
        }
      } else {
        console.log("[Diff] Conditions not met for fetching original content:", {
          hasContribution: !!contribution,
          canSee: isPending || isAdmin || canReview,
          hasSkillId: !!contribution?.skill_id
        });
      }
    } catch (err) {
      console.error("Failed to load file content:", err);
      setContent("Error loading file content.");
    } finally {
      setContentLoading(false);
    }
  }, [contributionId, contribution, user, hasPermission, rootFolderName]);

  useEffect(() => {
    // Load contribution metadata to know skill_id and base_version
    api(`/api/skill-contributions/${contributionId}`)
      .then((c: any) => {
        setContribution(c);
      })
      .catch(err => console.error("Failed to load contribution metadata:", err));
  }, [contributionId]);

  useEffect(() => {
    loadFiles();
  }, [contributionId]);

  useEffect(() => {
    if (selectedPath) {
      // Find the file in the current files list to check if it's a text file
      const file = files.find(f => f.path === selectedPath);
      if (file?.is_text) {
        loadContent(selectedPath);
      } else {
        // If it's a new file (not in 'files' list yet but in 'diffStatus'), we assume it's text
        if (diffStatus[selectedPath]) {
          loadContent(selectedPath);
        } else {
          setContent(null);
        }
      }
    }
  }, [selectedPath, loadContent]); // Removed displayFiles to prevent flickering after auto-save

  // Use a ref to always have access to the latest content without re-creating handleSave
  const contentRef = useRef<string | null>(null);
  useEffect(() => {
    contentRef.current = content;
  }, [content]);

  const handleSave = useCallback(async () => {
    const currentContent = contentRef.current;
    if (!selectedPath || mode !== "edit" || currentContent === null || currentContent === lastSavedContent) return;

    setSaveStatus("saving");
    try {
      await api(`/api/skill-contributions/${contributionId}/files`, {
        method: "PUT",
        body: {
          path: selectedPath,
          content: currentContent,
        },
      });
      setLastSavedContent(currentContent);
      setSaveStatus("saved");
      loadDiffStatus();
    } catch (err) {
      console.error("[AutoSave] Failed to save file:", err);
      setSaveStatus("error");
    }
  }, [contributionId, selectedPath, mode, lastSavedContent, loadDiffStatus]);

  // Auto-save effect
  useEffect(() => {
    if (content === null || content === lastSavedContent) {
      setSaveStatus("idle");
      return;
    }

    const timer = setTimeout(() => {
      handleSave();
    }, 500); // 0.5 seconds debounce

    return () => clearTimeout(timer);
  }, [content, handleSave, lastSavedContent]);


  const handleCreateFile = async (parentPath?: string) => {
    let base = parentPath || rootFolderName;
    if (!base && contribution) {
      const { slugify } = await import("@/lib/utils");
      base = slugify(contribution.title.replace("Upload: ", ""));
    }
    if (!base) base = "skill";

    const name = prompt(`Enter file name inside ${base}/ (e.g. src/utils.py):`);
    if (!name) return;
    const fullPath = `${base}/${name.replace(/^\/+/, "")}`;
    try {
      await api(`/api/skill-contributions/${contributionId}/files`, {
        method: "PUT",
        body: {
          path: fullPath,
          content: ""
        },
      });
      await loadFiles();
      setSelectedPath(fullPath);
      setIsEditMode(true);
    } catch (err) {
      console.error("Failed to create file:", err);
    }
  };

  const handleCreateFolder = async (parentPath?: string) => {
    let base = parentPath || rootFolderName;
    if (!base && contribution) {
      const { slugify } = await import("@/lib/utils");
      base = slugify(contribution.title.replace("Upload: ", ""));
    }
    if (!base) base = "skill";

    const name = prompt(`Enter folder name inside ${base}/:`);
    if (!name) return;
    const folderPath = `${base}/${name.replace(/^\/+/, "")}`;
    const path = folderPath.endsWith("/") ? `${folderPath}.gitkeep` : `${folderPath}/.gitkeep`;
    try {
      await api(`/api/skill-contributions/${contributionId}/files`, {
        method: "PUT",
        body: {
          path: path,
          content: ""
        },
      });
      await loadFiles();
    } catch (err) {
      console.error("Failed to create folder:", err);
    }
  };

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !uploadTargetPath) return;

    const formData = new FormData();
    formData.append("file", file);
    const fullPath = `${uploadTargetPath}/${file.name}`;

    try {
      const queryPath = encodeURIComponent(fullPath);
      await apiUpload(`/api/skill-contributions/${contributionId}/upload?path=${queryPath}`, formData);

      await loadFiles();
      setSelectedPath(fullPath);
      setUploadTargetPath(null);
      e.target.value = "";
    } catch (err) {
      console.error("Failed to upload file:", err);
      alert("Upload failed");
    }
  };

  const triggerUpload = (parentPath: string) => {
    setUploadTargetPath(parentPath);
    setTimeout(() => {
      document.getElementById("file-upload")?.click();
    }, 10);
  };

  const handleDelete = async (path: string, type: "file" | "folder") => {
    if (path === rootFolderName) {
      alert("Cannot delete the root folder.");
      return;
    }
    if (path === `${rootFolderName}/SKILL.md`) {
      alert("Cannot delete the SKILL.md file.");
      return;
    }

    if (!confirm(`Are you sure you want to delete this ${type}: ${path}?`)) return;
    try {
      await api(`/api/skill-contributions/${contributionId}/files?path=${encodeURIComponent(path)}`, {
        method: "DELETE"
      });
      await loadFiles();
      if (selectedPath === path || selectedPath?.startsWith(path + "/")) {
        setSelectedPath(null);
        setContent(null);
      }
    } catch (err) {
      console.error("Failed to delete item:", err);
      alert("Delete failed: " + (err instanceof Error ? err.message : "Unknown error"));
    }
  };

  const handleRename = async (oldPath: string, type: "file" | "folder") => {
    if (oldPath === rootFolderName) {
      alert("Cannot rename the root folder.");
      return;
    }
    if (oldPath === `${rootFolderName}/SKILL.md`) {
      alert("Cannot rename the SKILL.md file.");
      return;
    }

    const oldName = oldPath.split("/").pop() || "";
    const newName = prompt(`Enter new name for ${type}:`, oldName);
    if (!newName || newName === oldName) return;

    const pathParts = oldPath.split("/");
    pathParts.pop();
    const newPath = [...pathParts, newName].join("/");

    try {
      await api(`/api/skill-contributions/${contributionId}/rename?old_path=${encodeURIComponent(oldPath)}&new_path=${encodeURIComponent(newPath)}`, {
        method: "POST"
      });
      await loadFiles();
      if (selectedPath === oldPath) {
        setSelectedPath(newPath);
      } else if (selectedPath?.startsWith(oldPath + "/")) {
        setSelectedPath(selectedPath.replace(oldPath, newPath));
      }
    } catch (err) {
      console.error("Failed to rename item:", err);
      alert("Rename failed: " + (err instanceof Error ? err.message : "Unknown error"));
    }
  };

  const toggleFolder = (path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const renderTree = (nodes: TreeNode[], level = 0) => {
    return nodes.map((node) => {
      if (node.name === ".gitkeep") return null;

      const isExpanded = expandedFolders.has(node.path);
      const isSelected = selectedPath === node.path;

      if (node.type === "folder") {
        return (
          <div key={node.path} className="flex flex-col group/folder">
            <div className="flex items-center hover:bg-muted/50 rounded-md transition-colors pr-2 group">
              <button
                onClick={() => toggleFolder(node.path)}
                className="flex items-center gap-1.5 flex-1 px-2 py-1.5 text-[13px] text-muted-foreground hover:text-foreground"
                style={{ paddingLeft: `${level * 16 + 8}px` }}
              >
                <span className={cn("material-symbols-outlined text-[18px]", isExpanded && "rotate-90")}>chevron_right</span>
                <span className="material-symbols-outlined text-[20px] text-amber-500/80">{isExpanded ? "folder_open" : "folder"}</span>
                <span className="truncate font-medium flex-1 text-left">{node.name}</span>
                <StatusBadge status={getNodeStatus(node)} />
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger
                  className="h-7 w-7 flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-muted rounded-md transition-all outline-none"
                  title="Actions"
                >
                  <span className="material-symbols-outlined text-[18px]">more_vert</span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  <DropdownMenuItem
                    onClick={() => handleCreateFile(node.path)}
                    className="gap-2"
                  >
                    <span className="material-symbols-outlined text-[18px]">add_box</span>
                    New File
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => handleCreateFolder(node.path)}
                    className="gap-2"
                  >
                    <span className="material-symbols-outlined text-[18px]">create_new_folder</span>
                    New Folder
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => triggerUpload(node.path)}
                    className="gap-2"
                  >
                    <span className="material-symbols-outlined text-[18px]">upload_file</span>
                    Upload File
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => handleRename(node.path, "folder")}
                    className="gap-2"
                    disabled={node.path === rootFolderName}
                  >
                    <span className="material-symbols-outlined text-[18px]">edit</span>
                    Rename
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    onClick={() => handleDelete(node.path, "folder")}
                    className="gap-2"
                    disabled={node.path === rootFolderName}
                  >
                    <span className="material-symbols-outlined text-[18px]">delete</span>
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            {isExpanded && node.children && renderTree(node.children, level + 1)}
          </div>
        );
      }

      return (
        <div
          key={node.path}
          className={cn(
            "flex items-center hover:bg-muted/30 rounded-md transition-all group",
            isSelected ? "bg-primary/10" : ""
          )}
        >
          <button
            onClick={() => setSelectedPath(node.path)}
            className={cn(
              "flex items-center gap-2 flex-1 px-2 py-1.5 text-[13px] text-left transition-all",
              isSelected ? "text-primary font-semibold" : "text-muted-foreground"
            )}
            style={{ paddingLeft: `${level * 16 + 32}px` }}
          >
            <span className="material-symbols-outlined text-[20px]">{node.name.endsWith(".md") ? "article" : "description"}</span>
            <span className="truncate flex-1">{node.name}</span>
            <StatusBadge status={getNodeStatus(node)} />
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger
              className={cn(
                "h-7 w-7 flex items-center justify-center transition-all mr-1 hover:bg-muted rounded-md outline-none",
                isSelected ? "opacity-100" : "opacity-0 group-hover:opacity-100"
              )}
              title="Actions"
            >
              <span className="material-symbols-outlined text-[18px]">more_vert</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem
                onClick={() => handleRename(node.path, "file")}
                className="gap-2"
                disabled={node.path === `${rootFolderName}/SKILL.md`}
              >
                <span className="material-symbols-outlined text-[18px]">edit</span>
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onClick={() => handleDelete(node.path, "file")}
                className="gap-2"
                disabled={node.path === `${rootFolderName}/SKILL.md`}
              >
                <span className="material-symbols-outlined text-[18px]">delete</span>
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      );
    });
  };
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-center bg-card">
        <div className="w-16 h-16 rounded-full bg-amber-100 flex items-center justify-center mb-4">
          <span className="material-symbols-outlined text-amber-600 text-3xl">lock</span>
        </div>
        <h3 className="text-lg font-bold text-foreground mb-2">Read Only Mode</h3>
        <p className="text-sm text-muted-foreground max-w-md">
          {error}
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="bg-card overflow-hidden flex flex-col lg:flex-row h-full">
        {/* Sidebar */}
        <div className="w-full lg:w-80 border-b lg:border-b-0 lg:border-r border-border bg-secondary/5 flex flex-col overflow-hidden shrink-0">
          <div className="px-5 py-4 border-b border-border bg-secondary/10 flex items-center justify-between">
            <h4 className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">Files</h4>
            <div className="flex gap-1">
              <input
                type="file"
                id="file-upload"
                className="hidden"
                onChange={handleUploadFile}
              />
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={loadFiles} title="Refresh">
                <span className="material-symbols-outlined text-sm">refresh</span>
              </Button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-3 no-scrollbar">
            {loading ? <div className="p-4 text-xs opacity-50">Loading...</div> : renderTree(fileTree)}
          </div>
          
        </div>

        {/* Main Area */}
        <div className="flex-1 flex flex-col bg-background overflow-hidden">
          {selectedPath ? (
            <>
              <div className="px-6 py-3 border-b border-border bg-muted/5 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono font-semibold bg-secondary/30 px-2 py-1 rounded border border-border/50 truncate max-w-[300px]">
                    {selectedPath}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  {selectedPath?.toLowerCase().endsWith('.md') && (
                    <div className="flex bg-muted p-0.5 rounded-lg border border-border/50">
                      <Button
                        variant={(isEditMode && !diffMode) ? "secondary" : "ghost"}
                        size="xs"
                        onClick={() => { setIsEditMode(true); setDiffMode(false); }}
                        className={cn("h-7 px-3 text-[10px] font-bold uppercase tracking-wider rounded-md", (isEditMode && !diffMode) && "shadow-sm")}
                      >
                        Edit
                      </Button>
                      <Button
                        variant={(!isEditMode && !diffMode) ? "secondary" : "ghost"}
                        size="xs"
                        onClick={() => { setIsEditMode(false); setDiffMode(false); }}
                        className={cn("h-7 px-3 text-[10px] font-bold uppercase tracking-wider rounded-md", (!isEditMode && !diffMode) && "shadow-sm")}
                      >
                        Preview
                      </Button>
                    </div>
                  )}

                  {mode === "review" && (
                    <Button
                      variant={diffMode ? "secondary" : "ghost"}
                      size="xs"
                      onClick={() => setDiffMode(!diffMode)}
                      className={cn("h-7 px-3 text-[10px] font-bold uppercase tracking-wider rounded-md gap-2", diffMode && "shadow-sm")}
                    >
                      <span className="material-symbols-outlined text-[16px]">difference</span>
                      Diff
                    </Button>
                  )}
                  <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-secondary/20 border border-border/40">
                    <span className={cn(
                      "w-1.5 h-1.5 rounded-full transition-all duration-300",
                      saveStatus === "saving" ? "bg-amber-500 animate-pulse" :
                        saveStatus === "saved" ? "bg-emerald-500" :
                          saveStatus === "error" ? "bg-destructive" : "bg-muted-foreground/30"
                    )} />
                    <span className="text-[10px] font-bold uppercase tracking-tighter text-muted-foreground min-w-[70px]">
                      {saveStatus === "saving" ? "Saving..." :
                        saveStatus === "saved" ? "All Saved" :
                          saveStatus === "error" ? "Save Error" : "Ready"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex-1 overflow-hidden">
                {contentLoading ? (
                  <div className="flex items-center justify-center h-full text-xs opacity-50">Loading content...</div>
                ) : content !== null ? (
                  diffMode ? (
                    <div className="h-full overflow-y-auto bg-muted/5 font-mono text-[12px] no-scrollbar">
                      <DiffViewer original={originalContent || ""} modified={content || ""} />
                    </div>
                  ) : selectedPath?.toLowerCase().endsWith('.md') && !isEditMode ? (
                    <div className="flex h-full divide-x divide-border">
                      <div className="flex-1 overflow-hidden bg-muted/5">
                        <textarea
                          className="w-full h-full p-6 md:p-8 font-mono text-[13px] bg-transparent outline-none resize-none no-scrollbar"
                          value={content}
                          onChange={(e) => setContent(e.target.value)}
                          placeholder="Enter markdown here..."
                        />
                      </div>
                      <div className="flex-1 overflow-y-auto p-6 md:p-8 no-scrollbar bg-muted/5">
                        <div className="markdown-content max-w-full">
                          <ReactMarkdown remarkPlugins={[remarkGfm, remarkFrontmatter]}>{content}</ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  ) : isEditMode ? (
                    <textarea
                      className="w-full h-full p-6 md:p-8 font-mono text-[13px] bg-transparent outline-none resize-none no-scrollbar"
                      value={content}
                      onChange={(e) => setContent(e.target.value)}
                      placeholder="Enter code or markdown here..."
                    />
                  ) : (
                    <div className="h-full overflow-y-auto p-6 md:p-8 no-scrollbar bg-muted/5">
                      <div className="markdown-content max-w-4xl mx-auto">
                        <ReactMarkdown remarkPlugins={[remarkGfm, remarkFrontmatter]}>{content}</ReactMarkdown>
                      </div>
                    </div>
                  )
                ) : (
                  <div className="flex items-center justify-center h-full text-xs opacity-50 text-center">
                    Binary file or no preview available.
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full opacity-30">
              <span className="material-symbols-outlined text-8xl mb-4">edit_note</span>
              <p className="text-sm font-bold uppercase tracking-widest">Select a file to start editing</p>
            </div>
          )}
        </div>
      </div>
      <style jsx global>{`
      .markdown-content {
        color: #1f2328;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
      }
      .markdown-content h1 { font-size: 2em; font-weight: 600; margin-top: 24px; margin-bottom: 16px; padding-bottom: .3em; border-bottom: 1px solid #d0d7de; }
      .markdown-content h2 { font-size: 1.5em; font-weight: 600; margin-top: 24px; margin-bottom: 16px; padding-bottom: .3em; border-bottom: 1px solid #d0d7de; }
      .markdown-content h3 { font-size: 1.25em; font-weight: 600; margin-top: 24px; margin-bottom: 16px; }
      .markdown-content p { margin-top: 0; margin-bottom: 16px; line-height: 1.6; }
      .markdown-content ul { list-style-type: disc; margin-bottom: 16px; padding-left: 2em; }
      .markdown-content ol { list-style-type: decimal; margin-bottom: 16px; padding-left: 2em; }
      .markdown-content li { margin-top: .25em; }
      .markdown-content code { padding: .2em .4em; margin: 0; font-size: 85%; white-space: break-spaces; background-color: rgba(175,184,193,0.2); border-radius: 6px; font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; }
      .markdown-content pre { padding: 16px; overflow: auto; font-size: 85%; line-height: 1.45; background-color: #f6f8fa; border-radius: 6px; margin-bottom: 16px; border: 1px solid #d0d7de; }
      .markdown-content pre code { padding: 0; margin: 0; font-size: 100%; word-break: normal; white-space: pre; background: transparent; border: 0; }
      .markdown-content blockquote { padding: 0 1em; color: #636c76; border-left: .25em solid #d0d7de; margin-bottom: 16px; }
      .markdown-content table { border-spacing: 0; border-collapse: collapse; margin-top: 0; margin-bottom: 16px; width: 100%; overflow: auto; border: 1px solid #d0d7de; }
      .markdown-content th, .markdown-content td { padding: 8px 13px; border: 1px solid #d0d7de; }
      .markdown-content th { background-color: #f6f8fa; font-weight: 600; }
      .markdown-content tr { background-color: #ffffff; border-top: 1px solid #d8dee4; }
      .markdown-content tr:nth-child(2n) { background-color: #f6f8fa; }
    `}</style>
    </>
  );
}

function DiffViewer({ original, modified }: { original: string; modified: string }) {
  // Normalize line endings to avoid CRLF vs LF issues
  const cleanOriginal = (original || "").replace(/\r\n/g, "\n");
  const cleanModified = (modified || "").replace(/\r\n/g, "\n");

  const diffs = diff.diffLines(cleanOriginal, cleanModified);

  let oldLineCount = 0;
  let newLineCount = 0;

  return (
    <div className="flex flex-col w-full h-full bg-background font-mono text-[13px] overflow-y-auto no-scrollbar">
      <div className="flex bg-muted/30 border-b border-border font-bold text-[10px] uppercase tracking-wider sticky top-0 z-10">
        <div className="w-[100px] px-4 py-2 border-r border-border text-center text-muted-foreground">Line</div>
        <div className="flex-1 px-4 py-2">Content</div>
      </div>

      <div className="flex-1">
        {diffs.map((part, i) => {
          const lines = part.value.split("\n");
          // Remove last empty line from split if it's there
          if (lines[lines.length - 1] === "") lines.pop();

          return lines.map((line, j) => {
            if (!part.added && !part.removed) {
              oldLineCount++;
              newLineCount++;
              return (
                <div key={`${i}-${j}`} className="flex hover:bg-muted/30 group border-b border-border/10">
                  <div className="w-[100px] flex shrink-0 border-r border-border/30 bg-muted/10 text-[10px] text-muted-foreground/50 select-none">
                    <span className="w-1/2 text-right pr-2 py-1">{oldLineCount}</span>
                    <span className="w-1/2 text-right pr-2 py-1">{newLineCount}</span>
                  </div>
                  <div className="flex-1 px-4 py-1 whitespace-pre-wrap break-all opacity-70 group-hover:opacity-100">{line || " "}</div>
                </div>
              );
            } else if (part.removed) {
              oldLineCount++;
              return (
                <div key={`${i}-${j}`} className="flex bg-destructive/10 border-b border-destructive/20 text-destructive-foreground group">
                  <div className="w-[100px] flex shrink-0 border-r border-destructive/20 bg-destructive/20 text-[10px] text-destructive-foreground/60 select-none">
                    <span className="w-1/2 text-right pr-2 py-1">{oldLineCount}</span>
                    <span className="w-1/2 text-right pr-2 py-1">-</span>
                  </div>
                  <div className="flex-1 px-4 py-1 whitespace-pre-wrap break-all font-medium">
                    <span className="mr-2 opacity-50">-</span>
                    {line}
                  </div>
                </div>
              );
            } else {
              newLineCount++;
              return (
                <div key={`${i}-${j}`} className="flex bg-emerald-500/10 border-b border-emerald-500/20 text-emerald-900 group">
                  <div className="w-[100px] flex shrink-0 border-r border-emerald-500/20 bg-emerald-500/20 text-[10px] text-emerald-900/60 select-none">
                    <span className="w-1/2 text-right pr-2 py-1">-</span>
                    <span className="w-1/2 text-right pr-2 py-1">{newLineCount}</span>
                  </div>
                  <div className="flex-1 px-4 py-1 whitespace-pre-wrap break-all font-medium">
                    <span className="mr-2 opacity-50">+</span>
                    {line}
                  </div>
                </div>
              );
            }
          });
        })}
      </div>
    </div>
  );
}
