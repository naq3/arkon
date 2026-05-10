"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SkillEditor } from "@/components/skills/skill-editor";
import { cn } from "@/lib/utils";

type Contribution = {
  id: string;
  skill_id: string | null;
  contributor_id: string;
  contributor_name: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export default function AdminContributionsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [contributions, setContributions] = useState<Contribution[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeContributionId, setActiveContributionId] = useState<string | null>(null);

  const loadContributions = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch all pending contributions using the new admin endpoint
      const data = await api<Contribution[]>("/api/admin/skill-contributions");
      setContributions(data);
    } catch (err) {
      console.error("Failed to load contributions:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user && user.role !== "admin") {
      router.push("/");
      return;
    }
    loadContributions();
  }, [user, router, loadContributions]);

  const handleApprove = async (id: string) => {
    if (!confirm("Are you sure you want to APPROVE and MERGE this contribution?")) return;
    try {
      await api(`/api/skill-contributions/${id}/approve`, { method: "POST" });
      alert("Contribution approved and merged successfully!");
      setActiveContributionId(null);
      loadContributions();
    } catch (err) {
      alert("Approval failed: " + (err instanceof Error ? err.message : "Unknown error"));
    }
  };

  const handleReject = async (id: string) => {
    if (!confirm("Are you sure you want to REJECT this contribution?")) return;
    try {
      await api(`/api/skill-contributions/${id}/reject`, { method: "POST" });
      alert("Contribution rejected.");
      setActiveContributionId(null);
      loadContributions();
    } catch (err) {
      alert("Rejection failed: " + (err instanceof Error ? err.message : "Unknown error"));
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader 
        title="Contribution Management" 
        description="Review and approve AI skill proposals from the team."
      />

      <div className="bg-card rounded-2xl border border-border/50 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <span className="material-symbols-outlined text-3xl text-muted-foreground animate-spin">progress_activity</span>
          </div>
        ) : contributions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
            <span className="material-symbols-outlined text-6xl opacity-20">rate_review</span>
            <p>No pending contributions at the moment.</p>
          </div>
        ) : (
          <div className="divide-y divide-border/50">
            {contributions.map((c) => (
              <div key={c.id} className="p-6 hover:bg-muted/30 transition-all flex items-center justify-between group">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="material-symbols-outlined text-primary text-2xl">edit_note</span>
                  </div>
                  <div>
                    <h3 className="font-serif text-lg font-bold group-hover:text-primary transition-colors">{c.title}</h3>
                    <p className="text-sm text-muted-foreground mt-1 line-clamp-1">{c.description || "No description provided."}</p>
                    <div className="flex items-center gap-3 mt-3 text-xs">
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <span className="material-symbols-outlined text-sm">person</span>
                        {c.contributor_name}
                      </span>
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <span className="material-symbols-outlined text-sm">calendar_today</span>
                        {new Date(c.created_at).toLocaleDateString()}
                      </span>
                      <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-bold uppercase tracking-wider text-[10px]">
                        Pending Review
                      </span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={() => setActiveContributionId(c.id)}
                    className="gap-2 border-primary/20 hover:bg-primary/5 text-primary"
                  >
                    <span className="material-symbols-outlined text-sm">visibility</span>
                    Review
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {activeContributionId && (
        <Dialog open onOpenChange={() => setActiveContributionId(null)}>
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
                      Submitted by <span className="font-bold text-foreground">{contributions.find(c => c.id === activeContributionId)?.contributor_name}</span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={() => handleReject(activeContributionId)}
                    className="h-8 gap-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-all"
                  >
                    <span className="material-symbols-outlined text-sm">close</span>
                    Reject
                  </Button>
                  <Button 
                    variant="default" 
                    size="sm" 
                    onClick={() => handleApprove(activeContributionId)}
                    className="h-8 gap-2 bg-[#c2652a] text-white hover:opacity-90 shadow-lg transition-all font-bold"
                  >
                    <span className="material-symbols-outlined text-sm">check_circle</span>
                    Approve & Merge
                  </Button>
                  <div className="w-px h-6 bg-border mx-1" />
                  <Button 
                    variant="ghost" 
                    size="icon-sm" 
                    onClick={() => setActiveContributionId(null)}
                    className="hover:bg-muted transition-all"
                  >
                    <span className="material-symbols-outlined text-lg">close</span>
                  </Button>
                </div>
              </div>
            </DialogHeader>
            <div className="flex-1 overflow-hidden">
              {/* Using SkillEditor in read-only mode (effectively, since admin won't save here usually, but it supports editing if needed) */}
              <SkillEditor contributionId={activeContributionId} />
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
