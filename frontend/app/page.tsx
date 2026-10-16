import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center gap-8 px-6 py-16">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-gold">Genshin Impact · Next.js migration</p>
      <h1 className="max-w-3xl font-serif text-5xl leading-tight tracking-tight text-ink">从文本，到关系。</h1>
      <p className="max-w-2xl text-lg leading-8 text-muted">Next.js、TypeScript、shadcn/ui 与 Tailwind CSS 的新前端入口已经建立。现有 Python + SQLite 接口继续提供资料。</p>
      <div><Link href="/characters"><Button size="lg">打开角色目录</Button></Link></div>
    </main>
  );
}
