// The last paper cycle's two reconciliations: at its check, and after its decision.
import { Alert, Badge, Group, List, Stack, Table, Text } from "@mantine/core";

import type { ReconciliationView } from "../../api/types";
import { Section } from "../../components/Section";
import { dateTime, money } from "../../lib/format";

const STATUS_COLOR = { match: "green", corrected: "blue", mismatch: "red" } as const;
const STAGE = { check: "At the check", decision: "After the decision" } as const;

function One({ found }: { found: ReconciliationView }) {
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text fw={600} size="sm">
          {STAGE[found.stage]}
        </Text>
        <Badge color={STATUS_COLOR[found.status]}>{found.status}</Badge>
        <Text size="xs" c="dimmed">
          {dateTime(found.at)} · {found.run_id}
        </Text>
      </Group>
      {found.differences.length > 0 && (
        <Alert color="red" title="Differences: trading halts">
          <List size="sm">
            {found.differences.map((d) => (
              <List.Item key={`${d.kind}-${d.subject}-${d.detail}`}>
                <b>{d.kind}</b> {d.subject}: {d.detail}
              </List.Item>
            ))}
          </List>
        </Alert>
      )}
      {found.inferred.length > 0 && (
        <Alert color="orange" title="Fills inferred on a day no run read (resume applies them)">
          <List size="sm">
            {found.inferred.map((f) => (
              <List.Item key={f}>{f}</List.Item>
            ))}
          </List>
        </Alert>
      )}
      {found.ended.length > 0 && (
        <List size="sm">
          {found.ended.map((e) => (
            <List.Item key={e}>{e}</List.Item>
          ))}
        </List>
      )}
      {found.cash.length > 0 && (
        <Table fz="sm" verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Cash</Table.Th>
              <Table.Th ta="right">Tyche</Table.Th>
              <Table.Th ta="right">IBKR settled</Table.Th>
              <Table.Th ta="right">IBKR pending</Table.Th>
              <Table.Th ta="right">Gap allowed</Table.Th>
              <Table.Th>Outcome</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {found.cash.map((c) => (
              <Table.Tr key={c.currency}>
                <Table.Td>{c.currency}</Table.Td>
                <Table.Td ta="right">{money(c.tyche, c.currency)}</Table.Td>
                <Table.Td ta="right">{money(c.broker_settled, c.currency)}</Table.Td>
                <Table.Td ta="right">{money(c.broker_pending, c.currency)}</Table.Td>
                <Table.Td ta="right">{money(c.allowed, c.currency)}</Table.Td>
                <Table.Td>{c.outcome}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

export function ReconciliationCard({ found }: { found: ReconciliationView[] }) {
  return (
    <Section title="Reconciliation">
      {found.length === 0 ? (
        <Text size="sm" c="dimmed">
          No paper cycle has run yet.
        </Text>
      ) : (
        <Stack gap="lg">
          {found.map((r) => (
            <One key={`${r.run_id}-${r.at}`} found={r} />
          ))}
        </Stack>
      )}
    </Section>
  );
}
