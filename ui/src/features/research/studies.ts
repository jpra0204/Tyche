// The four studies the Research page runs, in the order its tabs show them.
import type { StudyKind } from "../../api/types";

export interface Study {
  kind: StudyKind;
  label: string;
  command: string;
  records: string;
}

export const STUDIES: Study[] = [
  { kind: "walk_forward", label: "Walk-forward", command: "tyche walk-forward", records: "reports/walk_forward/" },
  { kind: "sweep", label: "Sweep", command: "tyche sweep", records: "reports/sweeps/" },
  { kind: "capital", label: "Capital", command: "tyche capital", records: "reports/capital/" },
  { kind: "profiles", label: "Profiles", command: "tyche compare-profiles", records: "reports/profiles/" },
];

// The study a tab or an address names, or walk-forward for anything else.
export function studyKind(value: string | null | undefined): StudyKind {
  return STUDIES.find((s) => s.kind === value)?.kind ?? "walk_forward";
}

export function study(kind: StudyKind): Study {
  const found = STUDIES.find((s) => s.kind === kind);
  if (found === undefined) throw new Error(`unknown study ${kind}`);
  return found;
}
