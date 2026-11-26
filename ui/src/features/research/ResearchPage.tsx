// Walk-forward, sweeps, capital and profile comparison: a tab each, with its form and
// its records. The tab is in the address, so coming back from a report keeps it.
import { Loader, Stack, Tabs, Text, Title } from "@mantine/core";
import { useSearchParams } from "react-router";

import type { StudyKind } from "../../api/types";
import { ErrorAlert } from "../../components/ErrorAlert";
import { Section } from "../../components/Section";
import { LastRun } from "../runs/RunPanel";
import { useCurrentRun } from "../runs/useRun";
import { STUDIES, studyKind } from "./studies";
import { CapitalForm, ProfilesForm, SweepForm, WalkForwardForm } from "./Forms";
import { StudyTable } from "./StudyTable";
import { useResearch } from "./useResearch";

export function ResearchPage() {
  const research = useResearch();
  const current = useCurrentRun();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab");
  const kind: StudyKind = studyKind(tab);

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Research</Title>
        <Text size="sm" c="dimmed">
          Studies beyond one backtest, each the same <code>tyche</code> command you would type,
          on cached history and never the holdout.
        </Text>
      </div>

      {research.isPending && <Loader />}
      {research.isError && <ErrorAlert error={research.error} />}
      {research.data && (
        <Tabs value={kind} onChange={(value) => value && setParams({ tab: value })} keepMounted={false}>
          <Tabs.List mb="md">
            {STUDIES.map((s) => (
              <Tabs.Tab key={s.kind} value={s.kind}>
                {s.label}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          {STUDIES.map((s) => (
            <Tabs.Panel key={s.kind} value={s.kind}>
              <Stack gap="lg">
                <Section title={`Run: ${s.command}`}>
                  {s.kind === "walk_forward" && <WalkForwardForm research={research.data} />}
                  {s.kind === "sweep" && <SweepForm research={research.data} />}
                  {s.kind === "capital" && <CapitalForm research={research.data} />}
                  {s.kind === "profiles" && <ProfilesForm />}
                </Section>
                <LastRun run={current.data} />
                <Section title={`Recorded in ${s.records}`}>
                  <StudyTable kind={s.kind} />
                </Section>
              </Stack>
            </Tabs.Panel>
          ))}
        </Tabs>
      )}
    </Stack>
  );
}
