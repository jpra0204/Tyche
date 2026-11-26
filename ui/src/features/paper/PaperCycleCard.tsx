// One paper cycle, `tyche paper run`, behind a confirmation: it connects to IB Gateway
// and may send orders to the paper account.
import { Alert, Button, Group, List, Modal, Select, Stack, Text } from "@mantine/core";
import { IconAlertTriangle, IconPlayerPlay } from "@tabler/icons-react";
import { useState } from "react";

import type { StatusView } from "../../api/types";
import { ErrorAlert } from "../../components/ErrorAlert";
import { Section } from "../../components/Section";
import { useStartRun } from "../runs/useRun";

export function PaperCycleCard({ status, running }: { status: StatusView; running: boolean }) {
  const start = useStartRun();
  const [riskProfile, setRiskProfile] = useState("default");
  const [asking, setAsking] = useState(false);
  const gateway = status.secrets.ib_gateway;
  const configOk = status.config.valid;
  const ready = gateway && configOk && !running;

  function run() {
    start.mutate(
      { command: "paper_run", risk_profile: riskProfile, confirmed: true },
      { onSettled: () => setAsking(false) },
    );
  }

  return (
    <Section title="Paper cycle">
      <Stack gap="sm">
        <Text size="sm">
          One decision cycle on the IBKR <b>paper</b> account, as <code>tyche paper run</code>{" "}
          does: read IBKR's fills, reconcile, decide on every session closed since the last
          decision, send the orders for the next open, reconcile again, save, alert.
        </Text>
        {!gateway && (
          <Alert color="orange" icon={<IconAlertTriangle />} title="IB Gateway is not set up">
            Set the IB Gateway connection in the workspace's <code>.env</code> (see the paper
            run guide), then refresh.
          </Alert>
        )}
        {!configOk && (
          <Alert color="red" title="The configuration does not pass its check">
            {status.config.error}
          </Alert>
        )}
        <Group align="flex-end">
          <Select
            label="Risk profile"
            description="One that fits the account's size"
            data={status.config.risk_profiles.length ? status.config.risk_profiles : ["default"]}
            value={riskProfile}
            onChange={(value) => value && setRiskProfile(value)}
            allowDeselect={false}
            w={220}
          />
          <Button
            color="orange"
            leftSection={<IconPlayerPlay size={16} />}
            disabled={!ready}
            onClick={() => setAsking(true)}
          >
            Run the paper cycle…
          </Button>
        </Group>
        {running && (
          <Text size="sm" c="dimmed">
            A run is going; the next can start when it ends.
          </Text>
        )}
        {start.isError && <ErrorAlert error={start.error} />}
      </Stack>

      <Modal opened={asking} onClose={() => setAsking(false)} title="Run the paper cycle now?" size="lg">
        <Stack gap="sm">
          <Text size="sm">
            Under the risk profile <b>{riskProfile}</b>, this will:
          </Text>
          <List size="sm" spacing={4}>
            <List.Item>connect to IB Gateway, on the paper account named in .env;</List.Item>
            <List.Item>read its fills and reconcile them with Tyche's records;</List.Item>
            <List.Item>
              if a session has closed since the last decision, decide and <b>send orders</b>{" "}
              for the next open to the paper account;
            </List.Item>
            <List.Item>save the state database and send the alerts to Discord.</List.Item>
          </List>
          {status.trading.stopped && (
            <Alert color="red" title="Trading is stopped">
              The cycle still reads and reconciles the account, but sends no new orders until
              the stop is lifted.
            </Alert>
          )}
          <Text size="xs" c="dimmed">
            Run it after the close; IB Gateway must be logged in to the paper account. Live
            trading is never run from the console.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setAsking(false)}>
              Cancel
            </Button>
            <Button color="orange" onClick={run} loading={start.isPending}>
              Run the paper cycle
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Section>
  );
}
