// The guardrails beside every risk profile, each checked as the active one.
import { Alert, Stack, Table, Text } from "@mantine/core";

import type { GuardrailsView, ProfileCheckView } from "../../api/types";
import { Section } from "../../components/Section";
import { money, percent } from "../../lib/format";

const ROWS: { label: string; profile: (p: NonNullable<ProfileCheckView["profile"]>) => string; ceiling: (g: GuardrailsView) => string }[] = [
  { label: "Risk per trade", profile: (p) => percent(p.risk_per_trade), ceiling: (g) => percent(g.max_risk_per_trade) },
  { label: "Open positions", profile: (p) => String(p.max_open_positions), ceiling: (g) => String(g.max_open_positions) },
  { label: "Position size", profile: (p) => percent(p.max_position_size), ceiling: (g) => percent(g.max_position_size) },
  { label: "Daily loss limit", profile: (p) => percent(p.daily_loss_limit), ceiling: (g) => percent(g.max_daily_loss_limit) },
  { label: "Drawdown kill", profile: (p) => percent(p.drawdown_kill), ceiling: (g) => percent(g.max_drawdown_kill) },
];

export function RiskTab({
  guardrails,
  profiles,
}: {
  guardrails: GuardrailsView | null | undefined;
  profiles: ProfileCheckView[];
}) {
  const valid = profiles.filter((p) => p.valid && p.profile);
  const invalid = profiles.filter((p) => !p.valid);

  return (
    <Stack gap="lg">
      <Section title="Risk profiles against the guardrails">
        <Text size="sm" c="dimmed" mb="sm">
          Each profile in <code>config/risk/</code> is checked as the active one, as{" "}
          <code>tyche config check --risk-profile</code> does. No profile may pass a
          guardrail, and a strategy's own limits may only be stricter.
        </Text>
        <Table.ScrollContainer minWidth={500}>
          <Table striped fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Limit</Table.Th>
                <Table.Th>Guardrail</Table.Th>
                {valid.map((p) => (
                  <Table.Th key={p.name}>{p.name}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {ROWS.map((row) => (
                <Table.Tr key={row.label}>
                  <Table.Td>{row.label}</Table.Td>
                  <Table.Td fw={600}>{guardrails ? row.ceiling(guardrails) : "–"}</Table.Td>
                  {valid.map((p) => (
                    <Table.Td key={p.name}>{p.profile ? row.profile(p.profile) : "–"}</Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {invalid.map((p) => (
          <Alert key={p.name} color="red" mt="sm" title={`${p.name}: does not pass`}>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {p.error}
            </Text>
          </Alert>
        ))}
      </Section>

      {guardrails && (
        <Section title="Money caps (paper and live)">
          {guardrails.money_caps.length === 0 ? (
            <Text size="sm" c="dimmed">
              None set.
            </Text>
          ) : (
            <Stack gap={4}>
              {guardrails.money_caps.map((cap) => (
                <Text key={cap.currency} size="sm">
                  {cap.currency}: capital {money(cap.capital, cap.currency)}
                  {cap.order ? `, each order ${money(cap.order, cap.currency)}` : ""}
                </Text>
              ))}
              <Text size="xs" c="dimmed">
                Long only and no leverage always. Backtests run without the money caps.
              </Text>
            </Stack>
          )}
        </Section>
      )}
    </Stack>
  );
}
