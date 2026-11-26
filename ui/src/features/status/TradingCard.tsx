import { Alert, Badge, List, Stack, Text } from "@mantine/core";
import { IconAlertOctagon, IconCircleCheck } from "@tabler/icons-react";

import type { HaltView, TradingView } from "../../api/types";
import { Field, Section } from "../../components/Section";
import { dateTime } from "../../lib/format";

function Halt({ title, halt, runbook }: { title: string; halt: HaltView; runbook: string }) {
  return (
    <Alert color="red" icon={<IconAlertOctagon />} title={`${title} since ${dateTime(halt.since)}`}>
      <List size="sm">
        {halt.reasons.map((reason) => (
          <List.Item key={reason}>{reason}</List.Item>
        ))}
      </List>
      <Text size="sm" mt="xs">
        Only resume lifts it: <code>tyche resume</code>, or Resume on the Paper page. Runbook:{" "}
        <code>{runbook}</code>
      </Text>
    </Alert>
  );
}

export function TradingCard({ trading }: { trading: TradingView }) {
  const badge = trading.stopped ? (
    <Badge color="red">Stopped</Badge>
  ) : (
    <Badge color="green" leftSection={<IconCircleCheck size={12} />}>
      Trading allowed
    </Badge>
  );

  return (
    <Section title="Trading" aside={badge}>
      <Stack gap="sm">
        {trading.state_unreadable && (
          <Alert color="orange" title="The state database cannot be read">
            {trading.state_unreadable}
          </Alert>
        )}
        {trading.kill ? (
          <Alert color="red" icon={<IconAlertOctagon />} title="Kill switch engaged">
            <Stack gap={4}>
              <Field label="Reason">{trading.kill.reason}</Field>
              <Field label="Flatten">{trading.kill.flatten ? "yes: sells every holding" : "no"}</Field>
              {trading.kill.engaged_at && (
                <Field label="Engaged">{dateTime(trading.kill.engaged_at)}</Field>
              )}
            </Stack>
          </Alert>
        ) : (
          <Field label="Kill switch">off</Field>
        )}
        {trading.drawdown_halt ? (
          <Halt title="Drawdown halt" halt={trading.drawdown_halt} runbook="docs/runbooks/kill-switch.md" />
        ) : (
          <Field label="Drawdown halt">none</Field>
        )}
        {trading.reconciliation_halt ? (
          <Halt
            title="Reconciliation halt"
            halt={trading.reconciliation_halt}
            runbook="docs/runbooks/reconciliation-mismatch.md"
          />
        ) : (
          <Field label="Reconciliation">no halt</Field>
        )}
      </Stack>
    </Section>
  );
}
