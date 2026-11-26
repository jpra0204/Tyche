import { Stack, Table, Text } from "@mantine/core";

import type { AccountView } from "../../api/types";
import { Field, Section } from "../../components/Section";
import { dateTime, money } from "../../lib/format";

export function AccountCard({ account }: { account: AccountView | null }) {
  if (account === null) {
    return (
      <Section title="Account">
        <Text size="sm" c="dimmed">
          No paper run has saved state yet. The first <code>tyche paper run</code> starts
          from IBKR's cash.
        </Text>
      </Section>
    );
  }

  return (
    <Section title="Account">
      <Stack gap="md">
        <Stack gap={4}>
          <Field label="Saved by">{account.run_id}</Field>
          <Field label="At">{dateTime(account.saved_at)}</Field>
          {account.cash.map((cash) => (
            <Field key={cash.currency} label={`Cash ${cash.currency}`}>
              {money(cash.settled, cash.currency)} settled
              {Number(cash.pending) !== 0 && `, ${money(cash.pending, cash.currency)} to settle`}
            </Field>
          ))}
        </Stack>

        <div>
          <Text size="sm" fw={600} mb={4}>
            Positions
          </Text>
          {account.positions.length === 0 ? (
            <Text size="sm" c="dimmed">
              None
            </Text>
          ) : (
            <Table striped withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Instrument</Table.Th>
                  <Table.Th ta="right">Shares</Table.Th>
                  <Table.Th ta="right">Cost</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {account.positions.map((p) => (
                  <Table.Tr key={p.instrument}>
                    <Table.Td>{p.instrument}</Table.Td>
                    <Table.Td ta="right">{p.quantity}</Table.Td>
                    <Table.Td ta="right">{p.cost}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </div>

        <div>
          <Text size="sm" fw={600} mb={4}>
            Orders working at IBKR
          </Text>
          {account.working_orders.length === 0 ? (
            <Text size="sm" c="dimmed">
              None
            </Text>
          ) : (
            <Table striped withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Order</Table.Th>
                  <Table.Th>Instrument</Table.Th>
                  <Table.Th>Side</Table.Th>
                  <Table.Th>Type</Table.Th>
                  <Table.Th ta="right">Shares left</Table.Th>
                  <Table.Th ta="right">Stop</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {account.working_orders.map((o) => (
                  <Table.Tr key={o.client_order_id}>
                    <Table.Td>
                      <code>{o.client_order_id}</code>
                    </Table.Td>
                    <Table.Td>{o.instrument}</Table.Td>
                    <Table.Td>{o.side}</Table.Td>
                    <Table.Td>{o.order_type}</Table.Td>
                    <Table.Td ta="right">{o.remaining}</Table.Td>
                    <Table.Td ta="right">{o.stop_price ?? "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </div>
      </Stack>
    </Section>
  );
}
