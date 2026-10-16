"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const REAL_CATALOG = "genshin-basics-2026-10-15-v2";

const navigation = [
  { href: "/characters", label: "角色目录", match: ["/characters", "/real-characters", "/real-character"] },
  { href: "/search", label: "文本检索", match: ["/search"] },
  { href: "/read", label: "原文阅读", match: ["/read"] },
  { href: "/graph", label: "人物关系", match: ["/graph"] },
  { href: "/materials", label: "素材清单", match: ["/materials"] },
  { href: "/about", label: "收录与纠错", match: ["/about"] },
];

function isCurrent(pathname: string, match: string[]) {
  return match.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function NavigationLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <>
      {navigation.map((item) => {
        const current = isCurrent(pathname, item.match);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={current ? "page" : undefined}
            className={`rounded-md px-3 py-2 text-sm transition-colors ${current ? "bg-green text-white" : "text-ink hover:bg-green/10 hover:text-green"}`}
          >
            {item.label}
          </Link>
        );
      })}
    </>
  );
}

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname() || "/";
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-4 focus:py-2 focus:text-sm focus:text-white">
        跳到主要内容
      </a>
      <header className="sticky top-0 z-40 border-b border-line/90 bg-paper/95 backdrop-blur" aria-label="全局导航">
        <div className="mx-auto flex min-h-16 max-w-7xl items-center justify-between gap-4 px-5 sm:px-8">
          <Link href="/" className="flex min-w-0 items-center gap-3" aria-label="原神文本档案首页">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-green font-serif text-lg text-white">档</span>
            <span className="min-w-0">
              <span className="block truncate font-serif text-lg leading-tight text-ink">原神文本档案</span>
              <span className="hidden text-[11px] leading-tight text-muted sm:block">角色、文本与关系的可追溯入口</span>
            </span>
          </Link>

          <nav className="hidden items-center gap-1 lg:flex" aria-label="主要页面">
            <NavigationLinks pathname={pathname} />
          </nav>

          <button
            type="button"
            className="inline-flex h-10 items-center rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink hover:bg-green/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green lg:hidden"
            aria-expanded={menuOpen}
            aria-controls="mobile-navigation"
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? "收起菜单" : "打开菜单"}
          </button>
        </div>
        {menuOpen ? (
          <nav id="mobile-navigation" className="border-t border-line bg-panel px-5 py-3 lg:hidden" aria-label="移动端主要页面">
            <div className="mx-auto grid max-w-7xl gap-1 sm:grid-cols-2">
              <NavigationLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} />
            </div>
          </nav>
        ) : null}
      </header>

      <div className="border-b border-gold/20 bg-gold/10 px-5 py-2.5 text-xs leading-5 text-ink sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold text-gold">数据边界</span>
          <span>角色目录是社区基础资料；文本、原文和关系图当前是原创合成样本；完整真实剧情尚未接入。</span>
          <Link className="font-medium text-green underline-offset-2 hover:underline" href={`/real-characters?catalog=${REAL_CATALOG}`}>
            查看真实角色入口
          </Link>
        </div>
      </div>

      <div id="main-content">{children}</div>
    </div>
  );
}
