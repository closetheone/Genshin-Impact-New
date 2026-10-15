import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { relationshipUsage } from "../web/model.mjs";

const sample = JSON.parse(readFileSync(new URL("../data/samples/story.json", import.meta.url), "utf8"));
const setup = (id = "relation:mentor") => {
  const view = structuredClone(sample);
  return { view, relation: view.relationships.find((item) => item.id === id) };
};
const inspect = (view, relation, purposes = ["export"]) => relationshipUsage(view, relation, purposes);

test("ordinary relationship has two usable complete groups", () => {
  const { view, relation } = setup();
  assert.deepEqual(inspect(view, relation), { status: "allowed", availableGroups: 2, totalGroups: 2, base: "allowed" });
});

test("allowed assertion cannot override restricted supporting passages", () => {
  const { view, relation } = setup("relation:internal-mentor");
  assert.equal(inspect(view, relation).status, "denied");
  assert.equal(inspect(view, relation).base, "allowed");
});

test("one complete alternative suffices; fragments never form a new group", () => {
  const { view, relation } = setup();
  view.passages.find((p) => p.id === "passage:03").source_id = "source:internal";
  assert.equal(inspect(view, relation).availableGroups, 1);
  view.passages.find((p) => p.id === "passage:31").source_id = "source:internal";
  assert.equal(inspect(view, relation).status, "denied");
});

test("relationship, endpoint, and entry sources can each block usage", () => {
  for (const target of ["relation", "endpoint", "entry"]) {
    const { view, relation } = setup();
    const record = target === "relation" ? relation : target === "endpoint"
      ? view.characters.find((c) => c.id === relation.to_id) : view.entries[0];
    record.source_id = "source:internal";
    assert.equal(inspect(view, relation).status, "denied", target);
  }
});

test("missing speaker metadata is uncertain, not permission", () => {
  const { view, relation } = setup();
  relation.evidence_groups = [["passage:03"]];
  view.passages.find((p) => p.id === "passage:03").speaker_id = "person:not-in-response";
  assert.equal(inspect(view, relation).status, "unknown");
});

test("missing passage, source, or source right remains uncertain", () => {
  for (const missing of ["passage", "source", "right"]) {
    const { view, relation } = setup();
    if (missing === "passage") view.passages = [];
    if (missing === "source") view.sources = [];
    if (missing === "right") delete view.sources[0].rights.export;
    assert.equal(inspect(view, relation).status, "unknown", missing);
  }
});

test("AI export requires both permissions in the same complete group", () => {
  const { view, relation } = setup();
  view.sources[0].rights.external_ai = "denied";
  view.sources[1].rights.external_ai = "allowed";
  // A new allowed source keeps the assertion and dependencies neutral.
  view.sources.push({ ...view.sources[0], id: "source:both", rights: { export: "allowed", external_ai: "allowed" } });
  for (const record of [relation, ...view.characters, ...view.entries]) record.source_id = "source:both";
  view.passages.find((p) => p.id === "passage:31").source_id = "source:internal";
  assert.equal(inspect(view, relation, ["export"]).status, "allowed");
  assert.equal(inspect(view, relation, ["external_ai"]).status, "allowed");
  assert.equal(inspect(view, relation, ["export", "external_ai"]).status, "denied");
});
