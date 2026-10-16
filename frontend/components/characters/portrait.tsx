"use client";

import Image from "next/image";
import { useState } from "react";
import { findArt, type Catalog, type Character } from "./types";

export function CharacterPortrait({ catalog, character, large = false }: { catalog: Catalog; character: Character; large?: boolean }) {
  const art = findArt(catalog, character);
  const [failed, setFailed] = useState(false);

  if (!art || failed) {
    return (
      <div className={`relative grid place-items-center overflow-hidden rounded-xl bg-green/10 text-green ${large ? "min-h-80" : "aspect-[4/3]"}`}>
        <span className={`${large ? "text-8xl" : "text-5xl"} font-serif`}>{character.name.slice(0, 1)}</span>
        <span className="absolute bottom-3 left-3 right-3 text-center text-xs text-muted">
          {art ? "图片暂不可用，可通过官网入口查看" : "暂无匹配图片 · 文字占位"}
        </span>
      </div>
    );
  }

  return (
    <div className={`relative overflow-hidden rounded-xl bg-green/5 ${large ? "min-h-80" : "aspect-[4/3]"}`}>
      <Image
        src={large ? art.portrait_url : art.thumbnail_url}
        alt={`${character.name} · 官网${large ? "立绘" : "头像"}`}
        fill
        sizes={large ? "(max-width: 768px) 100vw, 40vw" : "(max-width: 768px) 50vw, 25vw"}
        className="object-cover object-top transition duration-500 group-hover:scale-[1.03]"
        loading={large ? "eager" : "lazy"}
        unoptimized
        onError={() => setFailed(true)}
      />
      <span className="absolute bottom-2 left-2 rounded-full bg-ink/75 px-2 py-1 text-[11px] text-white">官网图片</span>
    </div>
  );
}
