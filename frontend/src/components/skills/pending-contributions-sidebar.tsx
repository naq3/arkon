"use client";

import React, { useEffect, useCallback, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export type PendingContribution = {
  id: string;
  title: string;
  skill_id?: string | null;
  contributor_name: string;
  status: string;
  created_at: string;
};

type PendingContributionsSidebarProps = {
  onReview: (id: string) => void;
  onDataUpdate?: (data: PendingContribution[]) => void;
  contributions?: PendingContribution[]; // External data for controlled display
  refreshInterval?: number; // in milliseconds
  skillId?: string;
};

export function PendingContributionsSidebar({
  onReview,
  onDataUpdate,
  contributions: externalContributions,
  refreshInterval = 30000, // Default 30s
  skillId,
}: PendingContributionsSidebarProps) {
  const { canAccess, hasPermission } = useAuth();
  const [internalContributions, setInternalContributions] = useState<PendingContribution[]>([]);
  const [loading, setLoading] = useState(false);

  // Use external contributions if provided, otherwise fallback to internal state
  const contributions = externalContributions !== undefined ? externalContributions : internalContributions;

  const loadPending = useCallback(async () => {
    if (!canAccess("skill", "review") && !hasPermission("skill:contribution:review")) return;
    
    try {
      const url = skillId 
        ? `/api/admin/skill-contributions?skill_id=${skillId}` 
        : "/api/admin/skill-contributions";
      const data = await api<PendingContribution[]>(url);
      setInternalContributions(data);
      onDataUpdate?.(data);
    } catch (err) {
      console.error("Failed to load pending contributions:", err);
      // If we get a 403 or 401, we might want to stop polling or handle it
    }
  }, [canAccess, hasPermission]);

  // Initial load
  useEffect(() => {
    loadPending();
  }, [loadPending]);

  // Polling logic removed by user request

  if (contributions.length === 0) return null;

  return (
    <div className="bg-card rounded-2xl p-5 border border-border shadow-sahara flex flex-col animate-in fade-in slide-in-from-left-4 duration-700">
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-semibold text-foreground tracking-tight flex items-center gap-2">
          <span className="material-symbols-outlined text-primary/70 text-sm">rate_review</span>
          Pending Review
        </h4>
        <span className="bg-primary/10 text-primary text-[10px] font-bold px-2 py-0.5 rounded-full">
          {contributions.length}
        </span>
      </div>

      <div className="flex flex-col gap-1 max-h-[350px] overflow-y-auto custom-scrollbar -mx-1 px-1">
        {contributions.map((c) => (
          <button
            key={c.id}
            onClick={() => {
              onReview(c.id);
            }}
            className="group flex flex-col items-start gap-0.5 px-3 py-2.5 rounded-xl transition-all duration-300 text-left hover:bg-secondary/40 border border-transparent hover:border-border/40"
          >
            <div className="flex items-center justify-between w-full gap-2">
              <span className="text-[13px] font-bold text-foreground truncate group-hover:text-primary transition-colors font-manrope">
                {c.skill_id ? c.title : `Create skill: ${c.title || "Untitled Skill"}`}
              </span>
              <span className="material-symbols-outlined text-[14px] text-muted-foreground/20 group-hover:text-primary/40 transition-all">
                arrow_forward
              </span>
            </div>
            <div className="flex items-center gap-2 w-full">
              <span className="text-[10px] text-muted-foreground/60 truncate font-medium">
                by {c.contributor_name}
              </span>
              <span className="text-[10px] text-muted-foreground/30">•</span>
              <span className="text-[10px] text-muted-foreground/40 font-medium">
                {new Date(c.created_at).toLocaleString('en-GB', { 
                  day: '2-digit', 
                  month: '2-digit', 
                  year: 'numeric', 
                  hour: '2-digit', 
                  minute: '2-digit',
                  hour12: false 
                }).replace(',', '')}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
