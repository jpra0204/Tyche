// Every recorded study of one kind, newest first, each with its report.
import { Badge, Button, Group, Loader, Table, Text, Tooltip } from "@mantine/core";
import { IconFileText, IconRefresh } from "@tabler/icons-react";
import { Link } from "react-router";

import type { StudyKind, StudySummary } from "../../api/types";
import { ErrorAlert } from "../../components/ErrorAlert";
import { dateTime } from "../../lib/format";
import { useCurrentRun, useStartRun } from "../runs/useRun";
import { useStudies } from "./useResearch";

function Outcome({ study }: { study: StudySummary }) {
  if (study.error) {
    return (
      <Tooltip label={study.error} multiline w={360}>
        <Badge color="orange">Unreadable</Badge>
      </Tooltip>
    );
  }
  if (study.completed === false) return <Badge color="red">Incomplete</Badge>;
  return <Badge color="green">Recorded</Badge>;
}

function ReportButton({ study }: { study: StudySummary }) {
  const start = useStartRun();
  const running = useCurrentRun().data?.state === "running";
  if (study.has_report) {
    return (
      <Button
        component={Link}
        to={`/research/${study.kind}/${study.study_id}`}
        size="xs"
        variant="light"
        leftSection={<IconFileText size={14} />}
      >
        Report
      </Button>
    );
  }
  return (
    <Button
      size="xs"
      variant="default"
      leftSection={<IconRefresh size={14} />}
      disabled={running}
      onClick={() => start.mutate({ command: "report", run_id: study.study_id })}
    >
      Write report
    </Button>
  );
}

export function StudyTable({ kind }: { kind: StudyKind }) {
  const studies = useStudies(kind);
  if (studies.isPending) return <Loader />;
  if (studies.isError) return <ErrorAlert error={studies.error} />;
  if (studies.data.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        None recorded in this workspace yet.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={800}>
      <Table striped highlightOnHover verticalSpacing="xs" fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Started</Table.Th>
            <Table.Th>Range</Table.Th>
            <Table.Th>What it found</Table.Th>
            <Table.Th miw={130}>Outcome</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {studies.data.map((s) => (
            <Table.Tr key={s.study_id}>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                {s.started_at ? dateTime(s.started_at) : s.study_id}
              </Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                {s.first && s.last ? (
                  <>
                    {s.first}
                    <br />
                    {s.last}
                  </>
                ) : (
                  "–"
                )}
              </Table.Td>
              <Table.Td>{s.headline ?? s.error ?? "–"}</Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                <Outcome study={s} />
              </Table.Td>
              <Table.Td>
                <Group justify="flex-end" wrap="nowrap">
                  <ReportButton study={s} />
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
