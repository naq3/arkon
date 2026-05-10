"use client";

import { api, apiUpload, ApiError } from "@/lib/api";
import { useEffect, useState, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkFrontmatter from "remark-frontmatter";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Skill } from "@/components/skills/skill-card";
import { EmptyState } from "@/components/shared/empty-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SkillFileExplorer } from "@/components/skills/skill-file-explorer";
import { SkillContributeDialog as ContributeDialog } from "@/components/skills/skill-contribute-dialog";
import { SkillEditor } from "@/components/skills/skill-editor";
import { PendingContributionsSidebar, PendingContribution } from "@/components/skills/pending-contributions-sidebar";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface SkillVersion {
  version_number: number;
  created_at: string;
  changelog?: string;
}

export default function SkillDetailPage() {
  const { slug } = useParams();
  const router = useRouter();
  const { canAccess, hasPermission } = useAuth();
  const [skill, setSkill] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const [isSettingLatest, setIsSettingLatest] = useState(false);
  const [activeContributionId, setActiveContributionId] = useState<string | null>(null);
  const [reviewContributionId, setReviewContributionId] = useState<string | null>(null);
  const [pendingContributions, setPendingContributions] = useState<PendingContribution[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    async function loadSkill() {
      try {
        setLoading(true);
        setNotFound(false);
        const url = viewingVersion 
          ? `/api/skills/${slug}?version=${viewingVersion}` 
          : `/api/skills/${slug}`;
        const data = await api<Skill>(url);
        setSkill(data);
        if (!viewingVersion) setViewingVersion(data.current_version);
      } catch (error) {
        console.error("Failed to load skill:", error);
        if (error instanceof ApiError && error.status === 404) {
          setNotFound(true);
        }
      } finally {
        setLoading(false);
      }
    }
    if (slug) loadSkill();
  }, [slug, viewingVersion]);

  useEffect(() => {
    async function loadVersions() {
      try {
        const data = await api<SkillVersion[]>(`/api/skills/${slug}/versions`);
        setVersions(data);
      } catch (error) {
        console.error("Failed to load versions:", error);
      }
    }
    if (slug) loadVersions();
  }, [slug]);

  const handleDelete = async () => {
    if (!skill || !confirm(`Are you sure you want to delete ${skill.name}?`)) return;
    try {
      await api(`/api/skills/${skill.slug}`, { method: "DELETE" });
      router.push("/skills");
    } catch (error) {
      alert("Failed to delete skill");
    }
  };

  const handleSetLatest = async () => {
    if (!skill || !viewingVersion || isSettingLatest) return;
    if (!confirm(`Are you sure you want to set Version ${viewingVersion} as the official latest version?`)) return;

    try {
      setIsSettingLatest(true);
      await api(`/api/skills/${slug}/set-latest?version=${viewingVersion}`, { method: "POST" });
      alert(`Version ${viewingVersion} is now the latest.`);
      window.location.reload();
    } catch (error) {
      alert("Failed to set latest version");
    } finally {
      setIsSettingLatest(false);
    }
  };

  const handleZipUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !skill) return;

    // Enforce filename match (skill.name + ".zip")
    const expectedName = `${skill.name}.zip`;
    if (file.name !== expectedName) {
      alert(`Filename mismatch! You must upload a file named exactly "${expectedName}".`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    try {
      setIsUploading(true);
      const formData = new FormData();
      formData.append("file", file);

      const result = await apiUpload<{status: string, message: string}>(`/api/skills/${slug}/reupload`, formData);
      
      if (result.status === "skipped") {
        alert(result.message);
      } else {
        // Reload to show new version and updated documentation
        window.location.reload();
      }
    } catch (error) {
      const msg = error instanceof ApiError ? (error.data as any)?.detail : "Upload failed";
      alert("Error: " + msg);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleSubmitContribution = async () => {
    if (!activeContributionId) return;
    if (!confirm("Are you sure you want to submit this contribution for review?")) return;
    
    try {
      await api(`/api/skill-contributions/${activeContributionId}/submit`, { method: "POST" });
      alert("Contribution submitted successfully!");
      setActiveContributionId(null);
      window.location.reload();
    } catch (err) {
      console.error("Failed to submit contribution:", err);
      alert("Submit failed: " + (err instanceof Error ? err.message : "Unknown error"));
    }
  };
  
  const handleApprove = async (id: string) => {
    if (!confirm("Are you sure you want to APPROVE and MERGE this contribution?")) return;
    try {
      await api(`/api/skill-contributions/${id}/approve`, { method: "POST" });
      alert("Contribution approved and merged successfully!");
      setReviewContributionId(null);
      window.location.reload(); // Reload to see changes
    } catch (err) {
      alert("Approval failed: " + (err instanceof Error ? err.message : "Unknown error"));
      setReviewContributionId(null);
      setPendingContributions(prev => prev.filter(c => c.id !== id));
    }
  };

  const handleReject = async (id: string) => {
    if (!confirm("Are you sure you want to REJECT this contribution?")) return;
    try {
      await api(`/api/skill-contributions/${id}/reject`, { method: "POST" });
      alert("Contribution rejected.");
      setReviewContributionId(null);
      setPendingContributions(prev => prev.filter(c => c.id !== id));
    } catch (err) {
      alert("Rejection failed: " + (err instanceof Error ? err.message : "Unknown error"));
      setReviewContributionId(null);
      setPendingContributions(prev => prev.filter(c => c.id !== id));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <span className="material-symbols-outlined text-4xl text-muted-foreground animate-spin">
          progress_activity
        </span>
      </div>
    );
  }

  if (!skill) {
    if (notFound) {
      return (
        <div className="flex flex-col gap-8 py-12 animate-in fade-in duration-500">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <button 
              onClick={() => router.push("/skills")}
              className="flex items-center hover:text-primary transition-colors"
            >
              <span className="material-symbols-outlined text-base mr-1">arrow_back</span>
              Back to Skills
            </button>
          </div>
          <EmptyState
            icon="search_off"
            title="Skill Not Found"
            description={`We couldn't find a skill with the identifier "${slug}". It might have been deleted or moved.`}
            action={
              <Button onClick={() => router.push("/skills")} variant="outline" className="mt-4 shadow-sahara rounded-xl font-bold uppercase tracking-widest text-[11px] h-11 px-8">
                Return to Library
              </Button>
            }
          />
        </div>
      );
    }
    return null;
  }

  const dateStr = new Date(skill.updated_at).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="flex flex-col gap-8 pb-12 animate-in fade-in duration-500">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <button 
          onClick={() => router.push("/skills")}
          className="flex items-center hover:text-primary transition-colors"
        >
          <span className="material-symbols-outlined text-base mr-1">arrow_back</span>
          Back to Skills
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        <div className="lg:col-span-3 space-y-6">
          <SkillFileExplorer 
            skillId={skill.id} 
            version={viewingVersion} 
          />
        </div>

        <div className="lg:col-span-1 space-y-6">
          <div className="flex items-center justify-end w-full gap-3 animate-in fade-in slide-in-from-right-4 duration-500">
            {!skill.is_system && canAccess("skill", "create") && (
              <>
                <div>
                  <ContributeDialog
                    skillId={skill.id}
                    skillName={skill.name}
                    versions={versions}
                    onContributionCreated={(id) => setActiveContributionId(id)}
                  />
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 px-3 gap-2 font-bold uppercase tracking-wider border-primary/20 hover:bg-primary/5 transition-all whitespace-nowrap"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading}
                  title="Upload ZIP"
                >
                  <span className={cn("material-symbols-outlined text-sm", isUploading && "animate-spin")}>
                    {isUploading ? "progress_activity" : "publish"}
                  </span>
                  <span className="text-[10px]">ZIP</span>
                </Button>
                <input
                  type="file"
                  ref={fileInputRef}
                  className="hidden"
                  accept=".zip"
                  onChange={handleZipUpload}
                />
              </>
            )}
            {!skill.is_system && canAccess("skill", "delete") && (
              <Button
                variant="destructive"
                size="sm"
                onClick={handleDelete}
                className="h-9 w-9 p-0 transition-all shrink-0"
                title="Delete Skill"
              >
                <span className="material-symbols-outlined text-sm">delete</span>
              </Button>
            )}
          </div>

          <div className="bg-card rounded-xl border border-border p-8 space-y-8">
            <section>
              <h4 className="text-xs font-bold text-muted-foreground uppercase mb-4 tracking-wider">Status</h4>
              <div className="flex items-center gap-3">
                <Badge 
                  variant="outline"
                  className={cn(
                    "px-3 py-1.5 text-xs font-bold uppercase tracking-widest rounded-full flex items-center border",
                    skill.status === "active" 
                      ? "bg-green-500/10 text-green-600 border-green-500/20" 
                      : "bg-yellow-500/10 text-yellow-600 border-yellow-500/20"
                  )}
                >
                  {skill.status}
                </Badge>
              </div>
            </section>
            
            <section>
              <div className="flex items-center justify-between mb-4">
                <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Version History</h4>
                {viewingVersion !== skill.current_version && (
                  <Badge variant="outline" className="bg-yellow-500/10 text-yellow-600 border-yellow-500/20 text-[10px] font-bold">
                    PREVIEWING OLD
                  </Badge>
                )}
              </div>
              <div className="space-y-3">
                <Select 
                  value={viewingVersion?.toString() || ""} 
                  onValueChange={(v) => setViewingVersion(v ? parseInt(v) : null)}
                >
                  <SelectTrigger className="w-full bg-secondary/5 border-primary/20 h-10">
                    <SelectValue placeholder="Select version" />
                  </SelectTrigger>
                  <SelectContent sideOffset={4} className="max-h-60">
                    {versions.map((v) => (
                      <SelectItem key={v.version_number} value={v.version_number.toString()}>
                        Version {v.version_number} 
                        {v.version_number === skill.current_version && " (Latest)"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                  {!skill.is_system && canAccess("skill", "edit") && viewingVersion !== skill.current_version && (
                    <Button 
                      className="w-full bg-primary text-primary-foreground shadow-sahara font-bold text-[11px] uppercase tracking-wider h-10 animate-in fade-in slide-in-from-top-1"
                      onClick={handleSetLatest}
                      disabled={isSettingLatest}
                    >
                      {isSettingLatest ? "Setting..." : "Set as Official Latest"}
                    </Button>
                  )}
              </div>
            </section>

            {/* <section>
              <h4 className="text-xs font-bold text-muted-foreground uppercase mb-4 tracking-wider">Access</h4>
              <div className="text-xs font-mono break-all bg-secondary/30 p-4 rounded-xl border border-border text-muted-foreground leading-relaxed">
                {skill.version_hash || "N/A"}
              </div>
            </section> */}

            {/* Removed Contribution ZIP section from here */}
          </div>

          <PendingContributionsSidebar 
            skillId={skill.id}
            onReview={setReviewContributionId}
            onDataUpdate={setPendingContributions}
            refreshInterval={15000}
          />
        </div>
      </div>

      <style jsx global>{`
        .markdown-content {
          color: #1f2328;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
        }
        .markdown-content h1 { font-size: 2em; font-weight: 600; margin-top: 24px; margin-bottom: 16px; padding-bottom: .3em; border-bottom: 1px solid #d0d7de; }
        .markdown-content h2 { font-size: 1.5em; font-weight: 600; margin-top: 24px; margin-bottom: 16px; padding-bottom: .3em; border-bottom: 1px solid #d0d7de; }
        .markdown-content h3 { font-size: 1.25em; font-weight: 600; margin-top: 24px; margin-bottom: 16px; }
        .markdown-content p { margin-top: 0; margin-bottom: 16px; line-height: 1.5; }
        .markdown-content ul { list-style-type: disc; margin-bottom: 16px; padding-left: 2em; }
        .markdown-content ol { list-style-type: decimal; margin-bottom: 16px; padding-left: 2em; }
        .markdown-content li { margin-top: .25em; }
        .markdown-content code { padding: .2em .4em; margin: 0; font-size: 85%; white-space: break-spaces; background-color: rgba(175,184,193,0.2); border-radius: 6px; font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; }
        .markdown-content pre { padding: 16px; overflow: auto; font-size: 85%; line-height: 1.45; background-color: #f6f8fa; border-radius: 6px; margin-bottom: 16px; border: 1px solid #d0d7de; }
        .markdown-content pre code { padding: 0; margin: 0; font-size: 100%; word-break: normal; white-space: pre; background: transparent; border: 0; }
        .markdown-content blockquote { padding: 0 1em; color: #636c76; border-left: .25em solid #d0d7de; margin-bottom: 16px; }
        .markdown-content table { border-spacing: 0; border-collapse: collapse; margin-top: 0; margin-bottom: 16px; width: 100%; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
        .markdown-content th, .markdown-content td { padding: 8px 16px; border: 1px solid var(--border); }
        .markdown-content th { background-color: rgba(194, 101, 42, 0.05); font-weight: 700; }
        .markdown-content tr { background-color: transparent; }
        .markdown-content tr:nth-child(2n) { background-color: rgba(58, 48, 42, 0.02); }
      `}</style>

      {activeContributionId && (
        <Dialog open onOpenChange={() => setActiveContributionId(null)}>
          <DialogContent showCloseButton={false} className="!max-w-[98vw] w-[1800px] h-[96vh] p-0 gap-0 overflow-hidden rounded-xl border border-border shadow-2xl flex flex-col fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
            <DialogHeader className="p-4 border-b border-border shrink-0 bg-primary/5">
              <div className="flex items-center justify-between pr-8">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                    <span className="material-symbols-outlined text-primary">edit_note</span>
                  </div>
                  <div>
                    <DialogTitle className="text-xl font-serif">Editing Contribution</DialogTitle>
                    <p className="text-xs text-muted-foreground font-manrope">Draft Mode</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button 
                    id="force-submit-button"
                    onClick={handleSubmitContribution}
                    className="h-8 px-4 flex items-center justify-center bg-[#c2652a] text-white rounded-lg font-bold text-xs uppercase tracking-wider hover:opacity-90 shadow-lg transition-all"
                  >
                    Contribute
                  </button>
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={async () => {
                      if (!confirm("Are you sure you want to delete this draft contribution? This action cannot be undone.")) return;
                      try {
                        const { api } = await import("@/lib/api");
                        await api(`/api/skill-contributions/${activeContributionId}`, { method: "DELETE" });
                        setActiveContributionId(null);
                        window.location.reload();
                      } catch (err) {
                        console.error("Failed to delete contribution:", err);
                        alert("Delete failed: " + (err instanceof Error ? err.message : "Unknown error"));
                      }
                    }}
                    className="h-8 w-8 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-all"
                    title="Delete Draft"
                  >
                    <span className="material-symbols-outlined text-lg">delete</span>
                  </Button>
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={() => setActiveContributionId(null)}
                    className="h-8 w-8 hover:bg-muted transition-all"
                    title="Close Editor"
                  >
                    <span className="material-symbols-outlined text-lg">close</span>
                  </Button>
                </div>
              </div>
            </DialogHeader>
            <div className="flex-1 overflow-hidden">
              <SkillEditor 
                contributionId={activeContributionId} 
                mode="edit"
              />
            </div>
          </DialogContent>
        </Dialog>
      )}

      {reviewContributionId && (
        <Dialog open onOpenChange={() => setReviewContributionId(null)}>
          <DialogContent showCloseButton={false} className="!max-w-[98vw] w-[1800px] h-[96vh] p-0 gap-0 overflow-hidden rounded-xl border border-border shadow-2xl flex flex-col fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
            <DialogHeader className="p-4 border-b border-border shrink-0 bg-primary/5">
              <div className="flex items-center justify-between pr-8">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                    <span className="material-symbols-outlined text-primary">rate_review</span>
                  </div>
                  <div>
                    <DialogTitle className="text-xl font-serif">Review Contribution</DialogTitle>
                    <p className="text-xs text-muted-foreground font-manrope">
                      Submitted by <span className="font-bold text-foreground">{pendingContributions.find(c => c.id === reviewContributionId)?.contributor_name || "Unknown"}</span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={() => handleReject(reviewContributionId)}
                    className="h-8 gap-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-all"
                  >
                    <span className="material-symbols-outlined text-sm">close</span>
                    Reject
                  </Button>
                  <Button 
                    variant="default" 
                    size="sm" 
                    onClick={() => handleApprove(reviewContributionId)}
                    className="h-8 gap-2 bg-[#c2652a] text-white hover:opacity-90 shadow-lg transition-all font-bold"
                  >
                    <span className="material-symbols-outlined text-sm">check_circle</span>
                    Approve & Merge
                  </Button>
                  <div className="w-px h-6 bg-border mx-1" />
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={() => setReviewContributionId(null)}
                    className="h-8 w-8 hover:bg-muted transition-all"
                    title="Close Reviewer"
                  >
                    <span className="material-symbols-outlined text-lg">close</span>
                  </Button>
                </div>
              </div>
            </DialogHeader>
            <div className="flex-1 overflow-hidden">
              <SkillEditor 
                contributionId={reviewContributionId} 
                onStatusChange={() => {
                  setReviewContributionId(null);
                  window.location.reload();
                }}
              />
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
