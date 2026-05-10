import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SkillFileExplorer } from "./skill-file-explorer";
import { SkillContributeDialog as ContributeDialog } from "./skill-contribute-dialog";
import { SkillEditor } from "./skill-editor";

type SkillDetailDialogProps = {
  skillId: string;
  skillName: string;
  onClose: () => void;
};

export function SkillDetailDialog({
  skillId,
  skillName,
  onClose,
}: SkillDetailDialogProps) {
  const { user, hasPermission,canAccess } = useAuth();
  const [versions, setVersions] = useState<{ version_number: number }[]>([]);
  const [activeContributionId, setActiveContributionId] = useState<string | null>(null);

  useEffect(() => {
    const fetchVersions = async () => {
      try {
        const data = await api<any[]>(`/api/skills/${skillId}/versions`);
        setVersions(data);
      } catch (err) {
        console.error("Failed to fetch skill versions:", err);
      }
    };
    fetchVersions();
  }, [skillId]);

  if (activeContributionId) {
    return (
      <Dialog open onOpenChange={() => setActiveContributionId(null)}>
        <DialogContent className="max-w-[95vw] w-[1400px] h-[90vh] p-0 gap-0 overflow-hidden rounded-2xl border-border shadow-2xl flex flex-col">
          <DialogHeader className="p-4 border-b border-border shrink-0 bg-primary/5">
            <div className="flex items-center justify-between pr-8">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                  <span className="material-symbols-outlined text-primary">edit_note</span>
                </div>
                <div>
                  <DialogTitle className="text-xl font-heading">Editing Contribution</DialogTitle>
                  <p className="text-xs text-muted-foreground font-manrope">Draft Mode</p>
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setActiveContributionId(null)}>
                <span className="material-symbols-outlined text-sm mr-1">close</span> Close Editor
              </Button>
            </div>
          </DialogHeader>
          <div className="flex-1 overflow-hidden p-4">
            <SkillEditor 
              contributionId={activeContributionId} 
              mode="edit"
              onSubmitted={() => {
                alert("Contribution submitted successfully!");
                setActiveContributionId(null);
                onClose();
              }}
            />
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-6xl h-[85vh] p-0 gap-0 overflow-hidden rounded-2xl border-border shadow-2xl flex flex-col">
        <DialogHeader className="p-4 border-b border-border shrink-0 bg-secondary/10">
          <div className="flex items-center justify-between pr-8">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                <span className="material-symbols-outlined text-primary">terminal</span>
              </div>
              <div>
                <DialogTitle className="text-xl font-heading">{skillName}</DialogTitle>
                <p className="text-xs text-muted-foreground font-manrope">Package Explorer</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {(user?.role === "admin" || canAccess("skill", "create")) && (
                <ContributeDialog 
                  skillId={skillId} 
                  skillName={skillName} 
                  versions={versions} 
                  onContributionCreated={(id) => setActiveContributionId(id)}
                />
              )}
              <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-tighter bg-muted/50">
                {skillId.slice(0, 8)}
              </Badge>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-hidden p-4 bg-muted/5">
          <SkillFileExplorer skillId={skillId} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
