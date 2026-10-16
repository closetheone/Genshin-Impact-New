import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "原神文本档案",
  description: "角色资料、原文阅读与有出处的人物关系。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
