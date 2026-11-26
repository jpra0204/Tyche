// A run's command line, its state and everything it printed, kept scrolled to the end
// while it runs. The error stream is shown in red: the CLI writes `Error: …` there.
import { Badge, Box, Code, Group, Loader, ScrollArea, Text } from "@mantine/core";
import { useEffect, useRef } from "react";

import type { RunView } from "../../api/types";
import { Section } from "../../components/Section";
import { dateTime } from "../../lib/format";

function StateBadge({ run }: { run: RunView }) {
  switch (run.state) {
    case "running":
      return (
        <Badge color="blue" leftSection={<Loader size={10} color="white" />}>
          Running
        </Badge>
      );
    case "succeeded":
      return <Badge color="green">Done</Badge>;
    case "failed":
      return <Badge color="red">Failed (exit {run.exit_code})</Badge>;
  }
}

export function RunPanel({ run }: { run: RunView }) {
  const viewport = useRef<HTMLDivElement>(null);
  const count = run.lines.length;

  useEffect(() => {
    const element = viewport.current;
    if (element) element.scrollTo({ top: element.scrollHeight });
  }, [count]);

  return (
    <Section title={`Run ${run.number}`} aside={<StateBadge run={run} />}>
      <Group gap="xs" mb="xs">
        <Code>{run.argv.join(" ")}</Code>
        <Text size="xs" c="dimmed">
          started {dateTime(run.started_at)}
          {run.finished_at ? `, ended ${dateTime(run.finished_at)}` : ""}
        </Text>
      </Group>
      <ScrollArea.Autosize mah={420} viewportRef={viewport} type="auto">
        <Box
          component="pre"
          m={0}
          p="sm"
          fz="xs"
          ff="monospace"
          bg="var(--mantine-color-default-hover)"
          style={{ borderRadius: "var(--mantine-radius-sm)", whiteSpace: "pre-wrap" }}
        >
          {count === 0 ? (
            <Text span c="dimmed" fz="xs">
              {run.state === "running" ? "Starting…" : "It printed nothing."}
            </Text>
          ) : (
            run.lines.map((line, index) => (
              <Text
                key={index}
                span
                fz="xs"
                ff="monospace"
                c={line.stream === "err" ? "red" : undefined}
                display="block"
              >
                {line.text || " "}
              </Text>
            ))
          )}
        </Box>
      </ScrollArea.Autosize>
    </Section>
  );
}

// The last run, if there is one, for the pages that start runs.
export function LastRun({ run }: { run: RunView | null | undefined }) {
  return run ? <RunPanel run={run} /> : null;
}
