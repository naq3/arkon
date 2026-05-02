"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";

type NavItem = {
  label: string;
  href: string;
  icon: string;
  adminOnly?: boolean;
};

const navItems: NavItem[] = [
  { label: "Dashboard", href: "/", icon: "dashboard" },
  { label: "Knowledge Base", href: "/knowledge", icon: "database" },
  { label: "Knowledge Types", href: "/types", icon: "category", adminOnly: true },
  { label: "Departments", href: "/departments", icon: "business", adminOnly: true },
  { label: "Employees", href: "/employees", icon: "group", adminOnly: true },
  { label: "Roles", href: "/roles", icon: "admin_panel_settings", adminOnly: true },
  { label: "Projects", href: "/projects", icon: "folder_special" },
  { label: "Contacts", href: "/contacts", icon: "contacts" },
  { label: "Settings", href: "/settings", icon: "settings", adminOnly: true },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const filteredItems = navItems.filter(
    (item) => !item.adminOnly || isAdmin
  );

  return (
    <nav className="hidden md:flex fixed left-0 top-0 h-full w-60 border-r border-border bg-sidebar flex-col gap-2 p-5 z-40">
      {/* Brand */}
      <div className="mb-6 px-3">
        <Link href="/">
          <h1 className="text-xl font-heading text-primary tracking-tight">
            Arkon
          </h1>
        </Link>
      </div>

      {/* Navigation */}
      <div className="flex flex-col gap-1">
        {filteredItems.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-semibold translate-x-0.5"
                  : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground"
              )}
            >
              <span
                className={cn(
                  "material-symbols-outlined",
                  isActive && "filled"
                )}
              >
                {item.icon}
              </span>
              {item.label}
            </Link>
          );
        })}
      </div>

      {/* User info at bottom */}
      {user && (
        <div className="mt-auto pt-4 border-t border-border">
          <Link
            href="/profile"
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-sidebar-accent/50 transition-colors"
          >
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary text-xs font-bold">
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-medium text-foreground truncate">
                {user.name}
              </span>
              <span className="text-xs text-muted-foreground capitalize">
                {user.role}
              </span>
            </div>
          </Link>
        </div>
      )}
    </nav>
  );
}
