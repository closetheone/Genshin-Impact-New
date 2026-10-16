import { CharacterDetailPage } from "@/components/characters/character-detail";

export default async function RealCharacterByIdPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CharacterDetailPage id={id} />;
}
