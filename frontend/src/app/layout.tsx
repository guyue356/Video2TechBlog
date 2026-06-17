import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Video2TechBlog",
  description: "Transform Technical Videos into Publication-Ready Technical Articles",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full">
      <body className="h-full bg-white text-zinc-900 font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
