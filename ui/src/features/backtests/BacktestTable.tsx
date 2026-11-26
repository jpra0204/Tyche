// Every recorded backtest, newest first, each with its report.
import { Badge, Button, Group, Table, Text, Tooltip } from "@mantine/core";
import { IconFileText, IconRefresh } from "@tabler/icons-react";
import { Link } from "react-router";

import type { BacktestSummary } from "../../api/types";
import { money, percent } from "../../lib/format";
import { useCurrentRun, useStartRun } from "../runs/useRun";

function Outcome({ summary }: { summary: BacktestSummary }) {
  if (summary.error) {
    return (
      <Tooltip label={summary.error} multiline w={360}>
        <Badge color="orange">Unreadable</Badge>
      </Tooltip>
    );
  }
  if (summary.completed === false) {
    return (
      <Tooltip label={summary.failure ?? "the run did not complete"} multiline w={360}>
        <Badge color="red">Failed</Badge>
      </Tooltip>
    );
  }
  if (summary.halted) return <Badge color="red">Drawdown kill</Badge>;
  return <Badge color="green">Completed</Badge>;
}

function ReportButton({ summary }: { summary: BacktestSummary }) {
  const start = useStartRun();
  const running = useCurrentRun().data?.state === "running";
  if (summary.has_report) {
    return (
      <Button
        component={Link}
        to={`/backtests/${summary.run_id}`}
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
      onClick={() => start.mutate({ command: "report", run_id: summary.run_id })}
    >
      Write report
    </Button>
  );
}

const dash = (
  <Text span c="dimmed">
    –
  </Text>
);

export function BacktestTable({ backtests }: { backtests: BacktestSummary[] }) {
  if (backtests.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No backtest recorded in this workspace yet.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table striped highlightOnHover verticalSpacing="xs" fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Run</Table.Th>
            <Table.Th>Range</Table.Th>
            <Table.Th>Profile</Table.Th>
            <Table.Th ta="right">Final equity</Table.Th>
            <Table.Th ta="right">Return</Table.Th>
            <Table.Th ta="right">Benchmark</Table.Th>
            <Table.Th ta="right">Max drawdown</Table.Th>
            <Table.Th miw={130}>Outcome</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {backtests.map((b) => (
            <Table.Tr key={b.run_id}>
              <Table.Td ff="monospace" fz="xs" style={{ wordBreak: "break-all" }}>
                {b.run_id}
              </Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                {b.first && b.last ? (
                  <>
                    {b.first}
                    <br />
                    {b.last}
                  </>
                ) : (
                  dash
                )}
              </Table.Td>
              <Table.Td>{b.risk_profile ?? dash}</Table.Td>
              <Table.Td ta="right">
                {b.final_equity && b.currency ? money(b.final_equity, b.currency) : dash}
              </Table.Td>
              <Table.Td ta="right">{b.total_return ? percent(b.total_return) : dash}</Table.Td>
              <Table.Td ta="right">
                {b.benchmark_total_return ? (
                  <Tooltip label={b.benchmark ?? ""}>
                    <span>{percent(b.benchmark_total_return)}</span>
                  </Tooltip>
                ) : (
                  dash
                )}
              </Table.Td>
              <Table.Td ta="right">{b.max_drawdown ? percent(b.max_drawdown) : dash}</Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                <Outcome summary={b} />
              </Table.Td>
              <Table.Td>
                <Group justify="flex-end">
                  <ReportButton summary={b} />
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
