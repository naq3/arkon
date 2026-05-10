"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScopeBadge } from "@/components/shared/scope-badge";

function formatDateTime(dateStr: string) {
  const d = new Date(dateStr);
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const year = String(d.getFullYear()).slice(-2);
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  return `${day}/${month}/${year} ${hours}:${minutes}`;
}

type Contribution = {
  id: string;
  title: string;
  status: "draft" | "pending" | "approved" | "rejected";
  updated_at: string;
  scope_type: string;
  scope_ids: string[];
};

type Department = {
  id: string;
  name: string;
};

interface MySkillContributionsProps {
  onEdit: (id: string) => void;
  onRefreshNeeded: () => void;
  departments: Department[];
  refreshInterval?: number;
}

export function MySkillContributions({ onEdit, onRefreshNeeded, departments, refreshInterval = 15000 }: MySkillContributionsProps) {
  const [contributions, setContributions] = useState<Contribution[]>([]);
  const [loading, setLoading] = useState(true);

  const loadContributions = useCallback(async () => {
    try {
      const data = await api<Contribution[]>("/api/skill-contributions");
      // Only show active work (drafts and pending reviews)
      setContributions(data.filter(c => c.status !== "approved"));
    } catch (err) {
      console.error("Failed to load contributions:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadContributions();
  }, [loadContributions]);

  // Polling logic removed by user request

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this contribution?")) return;
    try {
      await api(`/api/skill-contributions/${id}`, { method: "DELETE" });
      loadContributions();
      onRefreshNeeded();
    } catch (err) {
      console.error("Failed to delete contribution:", err);
      alert("Delete failed");
    }
  };

  if (loading && contributions.length === 0) return null;
  if (contributions.length === 0) return null;

  return (
    <div className="bg-background/40 rounded-2xl border border-border/50 p-6 mb-8 animate-in fade-in slide-in-from-top-4 duration-500">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-sm font-bold uppercase tracking-widest text-muted-foreground flex items-center gap-2">
          <span className="material-symbols-outlined text-sm text-primary/60">pending_actions</span>
          Your Active Drafts & Proposals
        </h3>
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-bold text-muted-foreground/60 uppercase tracking-tight">
            {contributions.length} {contributions.length === 1 ? "proposal" : "proposals"}
          </span>
        </div>
      </div>

      <div className="bg-background/60 rounded-xl border border-border/40 overflow-hidden shadow-sm">
        <Table>
          <TableHeader className="bg-secondary/5">
            <TableRow className="hover:bg-transparent border-border/40">
              <TableHead className="w-[30%] h-11 text-[11px] font-bold uppercase tracking-wider text-muted-foreground pl-6">Contribution Proposal</TableHead>
              <TableHead className="w-[15%] h-11 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Visibility</TableHead>
              <TableHead className="w-[20%] h-11 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Departments</TableHead>
              <TableHead className="w-[10%] h-11 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Status</TableHead>
              <TableHead className="w-[15%] h-11 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Updated</TableHead>
              <TableHead className="w-[10%] h-11 text-right pr-6"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {contributions.map((c) => (
              <TableRow key={c.id} className="group hover:bg-primary/[0.01] border-border/40 transition-colors">
                <TableCell className="py-4 pl-6">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-primary/5 border border-primary/10 flex items-center justify-center shrink-0 group-hover:bg-primary/10 transition-colors">
                      <span className="material-symbols-outlined text-primary/60 text-[18px] group-hover:scale-110 transition-transform duration-300">
                        {c.status === "draft" ? "edit_note" : "mark_as_unread"}
                      </span>
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span
                        className="text-sm font-medium text-foreground truncate max-w-[250px] group-hover:text-primary transition-colors font-manrope cursor-pointer hover:underline underline-offset-4 decoration-primary/30"
                        onClick={() => {
                          if (c.status === "approved") {
                            setContributions(prev => prev.filter(item => item.id !== c.id));
                          } else {
                            onEdit(c.id);
                          }
                        }}
                      >
                        {c.title}
                      </span>
                    </div>
                  </div>
                </TableCell>

                <TableCell>
                  <ScopeBadge scopeType={c.scope_type} />
                </TableCell>

                <TableCell>
                  <div className="flex items-center gap-1.5 overflow-x-auto max-w-[180px] [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
                    {c.scope_type === "department" && c.scope_ids && c.scope_ids.length > 0 ? (
                      c.scope_ids.map((id) => {
                        const dept = departments.find(d => d.id === id);
                        return (
                          <div key={id} className="flex items-center gap-1 text-[10px] text-muted-foreground font-semibold uppercase tracking-wider bg-secondary/30 px-1.5 py-0.5 rounded-md shrink-0 whitespace-nowrap">
                            <span className="material-symbols-outlined text-[12px]">corporate_fare</span>
                            {dept?.name || "Loading..."}
                          </div>
                        );
                      })
                    ) : (
                      <div className="flex items-center gap-1 text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">
                        <span className="material-symbols-outlined text-[12px]">public</span>
                        Global
                      </div>
                    )}
                  </div>
                </TableCell>

                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      "w-2 h-2 rounded-full",
                      c.status === "draft" ? "bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.4)]" :
                        c.status === "pending" ? "bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.4)]" :
                          "bg-destructive shadow-[0_0_8px_rgba(239,68,68,0.4)]"
                    )} />
                    <span className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground/70">
                      {c.status}
                    </span>
                  </div>
                </TableCell>

                <TableCell>
                  <span className="text-xs text-muted-foreground tabular-nums font-manrope">
                    {formatDateTime(c.updated_at)}
                  </span>
                </TableCell>

                <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                  <DropdownMenu>
                    <DropdownMenuTrigger className="inline-flex items-center justify-center h-8 w-8 rounded-full hover:bg-secondary text-muted-foreground transition-colors focus:outline-none">
                      <span className="material-symbols-outlined text-lg">more_vert</span>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40 rounded-xl shadow-xl border-border">
                      <DropdownMenuItem
                        onClick={() => {
                          if (c.status === "approved") {
                            setContributions(prev => prev.filter(item => item.id !== c.id));
                          } else {
                            onEdit(c.id);
                          }
                        }}
                        className="flex items-center gap-2 py-2.5 cursor-pointer"
                      >
                        <span className="material-symbols-outlined text-base text-primary">edit</span>
                        Continue Editing
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => handleDelete(c.id)}
                        className="flex items-center gap-2 py-2.5 text-destructive focus:text-destructive cursor-pointer"
                      >
                        <span className="material-symbols-outlined text-base">delete</span>
                        Delete Draft
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
