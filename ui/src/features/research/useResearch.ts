import { useQuery } from "@tanstack/react-query";

import { useApi } from "../../api/context";
import type { StudyKind } from "../../api/types";

export function useResearch() {
  const api = useApi();
  return useQuery({ queryKey: ["research"], queryFn: () => api.getResearch() });
}

export function useStudies(kind: StudyKind) {
  const api = useApi();
  return useQuery({ queryKey: ["studies", kind], queryFn: () => api.listStudies(kind) });
}

export function useStudyReport(kind: StudyKind, studyId: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["studies", kind, studyId, "report"],
    queryFn: () => api.getStudyReport(kind, studyId),
  });
}
