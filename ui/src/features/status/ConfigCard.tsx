import { Alert, Badge, Code, Stack, Text } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";

import type { ConfigView, SecretsView } from "../../api/types";
import { Field, Section } from "../../components/Section";
import { money, percent } from "../../lib/format";

export function ConfigCard({ config, secrets }: { config: ConfigView; secrets: SecretsView }) {
  const badge = config.valid ? <Badge color="green">Valid</Badge> : <Badge color="red">Invalid</Badge>;

  return (
    <Section title="Configuration" aside={badge}>
      <Stack gap={4}>
        {!config.valid && (
          <Alert color="red" icon={<IconAlertTriangle />} title="tyche config check fails" mb="sm">
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {config.error}
            </Text>
          </Alert>
        )}
        {config.market_profile && <Field label="Market profile">{config.market_profile}</Field>}
        {config.risk_profile && (
          <Field label="Risk profile">
            <b>{config.risk_profile.name}</b>: {config.risk_profile.max_open_positions} position(s) up to{" "}
            {percent(config.risk_profile.max_position_size)} each; risk per trade{" "}
            {percent(config.risk_profile.risk_per_trade)}; daily loss limit{" "}
            {percent(config.risk_profile.daily_loss_limit)}; drawdown kill{" "}
            {percent(config.risk_profile.drawdown_kill)}
          </Field>
        )}
        {config.money_caps.map((cap) => (
          <Field key={cap.currency} label={`Money caps ${cap.currency}`}>
            capital {money(cap.capital, cap.currency)}
            {cap.order && `, one order ${money(cap.order, cap.currency)}`}
          </Field>
        ))}
        {config.strategies.length > 0 && (
          <Field label="Strategies">
            {config.strategies
              .map((s) => `${s.strategy_id} (${s.plugin}) ${percent(s.budget)}`)
              .join(", ")}
            {config.cash_budget && `; cash ${percent(config.cash_budget)}`}
          </Field>
        )}
        {config.config_hash && (
          <Field label="Config hash">
            <Code>{config.config_hash}</Code>
          </Field>
        )}
        <Field label="Discord">{secrets.discord_webhook ? "webhook set" : "not set: alerts are not sent"}</Field>
        <Field label="IB Gateway">
          {secrets.ib_gateway ? "connection set in .env" : "not set: needed by tyche paper run"}
        </Field>
        {secrets.error && (
          <Alert color="red" title=".env cannot be read" mt="sm">
            {secrets.error}
          </Alert>
        )}
      </Stack>
    </Section>
  );
}
