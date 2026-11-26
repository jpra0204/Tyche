// The configured strategies with their parameters and own limits, and the sweeps.
import { Alert, Badge, Group, SimpleGrid, Stack, Text } from "@mantine/core";

import type { StrategyDetailView, SweepView } from "../../api/types";
import { Field, Section } from "../../components/Section";
import { percent } from "../../lib/format";
import { Settings } from "./Settings";

function Strategy({ strategy }: { strategy: StrategyDetailView }) {
  const limits = [
    strategy.risk_per_trade ? `risk per trade ${percent(strategy.risk_per_trade)}` : null,
    strategy.max_open_positions ? `${strategy.max_open_positions} positions` : null,
    strategy.max_position_size ? `position size ${percent(strategy.max_position_size)}` : null,
  ].filter(Boolean);
  return (
    <Section
      title={strategy.strategy_id}
      aside={<Badge variant="light">budget {percent(strategy.budget)}</Badge>}
    >
      <Stack gap="xs">
        <Field label="Plugin">{strategy.plugin}</Field>
        <Field label="File">
          <code>{strategy.source}</code>
        </Field>
        <Field label="Own limits">{limits.length ? limits.join(", ") : "none: the profile's"}</Field>
        <Text size="sm" fw={600} mt="xs">
          Parameters
        </Text>
        <Settings settings={strategy.parameters} />
      </Stack>
    </Section>
  );
}

function Sweep({ sweep }: { sweep: SweepView }) {
  return (
    <Section
      title={sweep.name}
      aside={
        sweep.error ? (
          <Badge color="orange">cannot run</Badge>
        ) : (
          <Badge variant="light">{sweep.combinations} combinations</Badge>
        )
      }
    >
      {sweep.error ? (
        <Alert color="orange">{sweep.error}</Alert>
      ) : (
        <Stack gap="xs">
          <Field label="Varies">{sweep.strategy_id}</Field>
          <Settings settings={sweep.grid} />
        </Stack>
      )}
    </Section>
  );
}

export function StrategiesTab({
  strategies,
  cash,
  sweeps,
}: {
  strategies: StrategyDetailView[];
  cash: string | null | undefined;
  sweeps: SweepView[];
}) {
  return (
    <Stack gap="lg">
      <Group gap="xs">
        <Text size="sm" c="dimmed">
          Budgets are fractions of equity, from <code>config/tyche.toml</code>.
        </Text>
        {cash && <Badge variant="outline">cash {percent(cash)}</Badge>}
      </Group>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        {strategies.map((s) => (
          <Strategy key={s.strategy_id} strategy={s} />
        ))}
      </SimpleGrid>
      <Text fw={600}>Sweeps in config/sweeps/</Text>
      {sweeps.length === 0 ? (
        <Text size="sm" c="dimmed">
          None.
        </Text>
      ) : (
        <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
          {sweeps.map((s) => (
            <Sweep key={s.name} sweep={s} />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
