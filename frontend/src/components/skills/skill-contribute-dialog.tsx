"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { Checkbox } from "@/components/ui/checkbox";

type SkillContributeDialogProps = {
  skillId?: string;
  skillName?: string;
  versions?: { version_number: number }[];
  onContributionCreated: (contributionId: string) => void;
  trigger?: React.ReactElement;
  allDepartments?: { id: string, name: string }[];
};

export function SkillContributeDialog({ skillId, skillName, versions, onContributionCreated, trigger, allDepartments: externalDepartments }: SkillContributeDialogProps) {
  const { canAccess, hasPermission } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"new" | "fork">(skillId ? "fork" : "new");

  useEffect(() => {
    if (skillId) setMode("fork");
    else setMode("new");
  }, [skillId]);

  const [title, setTitle] = useState(skillName ? `Improve ${skillName}` : "");
  const [selectedVersion, setSelectedVersion] = useState<string | null>(
    versions && versions.length > 0 ? String(versions[0].version_number) : null
  );
  const [duplicateSkill, setDuplicateSkill] = useState<{ id: string, name: string } | null>(null);
  const [showDuplicateWarning, setShowDuplicateWarning] = useState(false);

  // New Visibility State (Matching Upload Form)
  const [scopeType, setScopeType] = useState<string>("global");
  const [deptIds, setDeptIds] = useState<string[]>([]);
  const [internalDepartments, setInternalDepartments] = useState<{ id: string, name: string }[]>([]);
  const allDepartments = externalDepartments || internalDepartments;

  useEffect(() => {
    if (!skillId && !externalDepartments) {
      api<any[]>("/api/departments")
        .then(res => setInternalDepartments(Array.isArray(res) ? res : []))
        .catch(err => {
          console.error("Failed to load departments:", err);
          setInternalDepartments([]);
        });
    }
  }, [skillId, externalDepartments]);

  const isTitleValid = mode === "fork" || /^[a-zA-Z0-9\s\-_À-ỹ]+$/.test(title);

  const performSubmit = async (finalSkillId: string | null, finalBaseVersion: number | null) => {
    try {
      const data = await api<{ id: string }>("/api/skill-contributions", {
        method: "POST",
        body: {
          skill_id: finalSkillId,
          base_version: finalBaseVersion,
          title,
          scope_type: finalSkillId ? "global" : scopeType,
          scope_ids: finalSkillId ? null : (scopeType === "department" ? deptIds : []),
        },
      });
      onContributionCreated(data.id);
      setIsOpen(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create contribution");
    } finally {
      setLoading(false);
    }
  };

  const handleContribute = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    if (mode === "new") {
      try {
        // Check for duplicates
        const res = await api<{ items: any[] }>(`/api/skills?q=${encodeURIComponent(title)}&limit=1`);
        const exactMatch = res.items.find(s => s.name.toLowerCase() === title.toLowerCase());

        if (exactMatch) {
          setDuplicateSkill({ id: exactMatch.id, name: exactMatch.name });
          setShowDuplicateWarning(true);
          setLoading(false);
          return;
        }
      } catch (err) {
        console.error("Failed to check for duplicates:", err);
      }
    }

    await performSubmit(
      mode === "fork" ? skillId || null : null,
      mode === "fork" ? (selectedVersion ? parseInt(selectedVersion) : null) : null
    );
  };

  const handleConfirmDuplicate = async () => {
    if (!duplicateSkill) return;
    setLoading(true);
    setShowDuplicateWarning(false);
    // Switch to fork mode logic effectively
    await performSubmit(duplicateSkill.id, null); // null base version defaults to latest
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      {(canAccess("skill", "create")) && (
        <DialogTrigger
          render={
            trigger || (
              <Button variant="outline" className="gap-2 border-primary/20 hover:bg-primary/5 text-primary">
                <span className="material-symbols-outlined text-sm">edit_square</span>
                Contribute
              </Button>
            )
          }
        />
      )}
      <DialogContent className="sm:max-w-[500px]">
        <form onSubmit={handleContribute}>
          <DialogHeader>
            <DialogTitle className="text-xl font-heading">
              {skillId ? `Contribute to ${skillName}` : "Create New Skill"}
            </DialogTitle>
            <DialogDescription className="font-manrope">
              {skillId
                ? "Propose changes to improve this skill."
                : "Propose a brand new skill to the Arkon platform."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-6 py-6">
            {!skillId && (
              <div className="grid gap-2">
                <Label htmlFor="title">Title</Label>
                <Input
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. SRS-writing-skill"
                  required
                  className={cn(!isTitleValid && "border-destructive focus-visible:ring-destructive")}
                />
                {!isTitleValid && (
                  <p className="text-[11px] text-destructive font-medium animate-in fade-in slide-in-from-top-1">
                    Title contains invalid characters. Use only letters, numbers, spaces, - and _.
                  </p>
                )}
              </div>
            )}

            {/* Visibility Selector - Only for New Skills (Matching Upload Form) */}
            {!skillId && (
              <>
                <div className="grid gap-2">
                  <Label>Visibility</Label>
                  <Select value={scopeType} onValueChange={(v) => {
                    if (v) setScopeType(v);
                    setDeptIds([]);
                  }}>
                    <SelectTrigger className="bg-secondary/5 h-11">
                      <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-base text-muted-foreground">
                          {scopeType === "global" ? "public" : "corporate_fare"}
                        </span>
                        <span className="capitalize">
                          {scopeType === "global" ? "Global" : "Department"}
                        </span>
                      </div>
                    </SelectTrigger>
                    <SelectContent className="min-w-[240px]">
                      <SelectItem value="global">
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-base text-muted-foreground">public</span>
                          Global (All Departments)
                        </div>
                      </SelectItem>
                      <SelectItem value="department">
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-base text-muted-foreground">corporate_fare</span>
                          Specific Departments
                        </div>
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {scopeType === "department" && (
                  <div className="grid gap-2 animate-in fade-in slide-in-from-top-1">
                    <Label>Target Departments</Label>
                    <div className="bg-secondary/5 rounded-xl border border-border p-3">
                      <div className="max-h-[160px] pr-4 overflow-y-auto custom-scrollbar">
                        <div className="grid grid-cols-1 gap-2">
                          {allDepartments.map((d) => (
                            <div key={d.id} className="flex items-center space-x-2 group/item">
                              <Checkbox
                                id={`contribute-dept-${d.id}`}
                                checked={deptIds.includes(d.id)}
                                onCheckedChange={(checked) => {
                                  if (checked) {
                                    setDeptIds([...deptIds, d.id]);
                                  } else {
                                    setDeptIds(deptIds.filter(id => id !== d.id));
                                  }
                                }}
                              />
                              <label
                                htmlFor={`contribute-dept-${d.id}`}
                                className="text-sm font-medium leading-none cursor-pointer group-hover/item:text-primary transition-colors"
                              >
                                {d.name}
                              </label>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}

            {mode === "fork" && skillId && versions && versions.length > 0 && (
              <div className="grid gap-2 animate-in fade-in slide-in-from-top-1">
                <Label>Base Version</Label>
                <Select value={selectedVersion || ""} onValueChange={setSelectedVersion}>
                  <SelectTrigger className="bg-secondary/5 h-11">
                    <SelectValue placeholder="Select version" />
                  </SelectTrigger>
                  <SelectContent>
                    {versions.map((v) => (
                      <SelectItem key={v.version_number} value={String(v.version_number)}>
                        Version {v.version_number}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button type="submit" disabled={loading || !isTitleValid || (scopeType === "department" && deptIds.length === 0)} className="w-full sm:w-auto px-8">
              {loading ? "Initializing..." : (skillId ? "Start Improving" : "Start Creating")}
            </Button>
          </DialogFooter>
        </form>

        {showDuplicateWarning && duplicateSkill && (
          <div className="absolute inset-0 bg-background/95 backdrop-blur-sm z-50 flex items-center justify-center p-6 animate-in fade-in zoom-in-95">
            <div className="bg-card border shadow-2xl rounded-2xl p-6 max-w-[400px] text-center space-y-4">
              <div className="w-16 h-16 bg-yellow-500/10 text-yellow-600 rounded-full flex items-center justify-center mx-auto">
                <span className="material-symbols-outlined text-3xl">warning</span>
              </div>
              <div className="space-y-2">
                <h3 className="text-xl font-serif font-bold italic">Skill Already Exists</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  A skill named <strong className="text-foreground">"{duplicateSkill.name}"</strong> already exists.
                  Would you like to contribute to the existing skill instead?
                </p>
              </div>
              <div className="flex flex-col gap-2 pt-2">
                <Button onClick={handleConfirmDuplicate} className="w-full">
                  Yes, contribute to existing
                </Button>
                <Button variant="ghost" onClick={() => setShowDuplicateWarning(false)} className="w-full">
                  No, I'll change the name
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
