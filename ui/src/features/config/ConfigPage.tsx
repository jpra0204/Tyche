// The workspace's configuration, read-only (U5). The files are edited in the workspace,
// by hand; this page shows what Tyche reads from them and whether it passes its check.
import {
  Accordion,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconCircleCheck, IconRefresh } from "@tabler/icons-react";
import { useSearchParams } from "react-router";

import type { MarketView, WorkspaceConfigView } from "../../api/types";
import { ErrorAlert } from "../../components/ErrorAlert";
import { Field, Section } from "../../components/Section";
import { dateTime, percent } from "../../lib/format";
import { RiskTab } from "./RiskTab";
import { Settings } from "./Settings";
import { StrategiesTab } from "./StrategiesTab";
import { useConfig } from "./useConfig";

const TABS = ["check", "risk", "strategies", "market", "files"] as const;
type Tab = (typeof TABS)[number];

function Check({ config }: { config: WorkspaceConfigView }) {
  return (
    <Stack gap="md">
      {config.valid ? (
        <Alert color="green" icon={<IconCircleCheck />} title="The configuration passes its check">
          As <code>tyche config check</code> reads it, under the <code>default</code> risk
          profile, with every strategy built from its file.
        </Alert>
      ) : (
        <Alert color="red" icon={<IconAlertTriangle />} title="The configuration does not pass">
          <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
            {config.error}
          </Text>
        </Alert>
      )}
      {config.env_readable_by_others && (
        <Alert color="orange" icon={<IconAlertTriangle />} title="Other users can read .env">
          Make it private: <Code>chmod 600 {config.workspace}/.env</Code>
        </Alert>
      )}
      <Section title="Fingerprint">
        <Stack gap={4}>
          <Field label="Workspace">
            <code>{config.workspace}</code>
          </Field>
          <Field label="Config hash">
            <code>{config.config_hash ?? "–"}</code>
          </Field>
          <Text size="xs" c="dimmed" mt="xs">
            Two runs with the same hash used the same configuration. Comments and key order
            do not change it; any value does. Secrets in <code>.env</code> are not part of
            it and are never shown here; the Status page says which are set.
          </Text>
        </Stack>
      </Section>
    </Stack>
  );
}

function Market({ market }: { market: MarketView }) {
  return (
    <Section title={`Market profile ${market.name}`}>
      <Stack gap={4}>
        <Field label="Cash currencies">{market.cash_currencies.join(", ")}</Field>
        <Field label="Calendars">{market.calendars.join(", ")}</Field>
        <Field label="Candidates">{market.candidates.join(", ")}</Field>
        <Field label="Benchmark">{market.benchmark}</Field>
        <Field label="Rebalance band">{percent(market.rebalance_band)}</Field>
        <Field label="Price buffer">{percent(market.price_buffer)}</Field>
        <Field label="Starting cash">{market.starting_cash} (backtests)</Field>
        <Field label="Holdout starts">
          {market.holdout_starts}: no backtest may reach it, and it never moves later
        </Field>
        <Field label="Costs checked">{market.costs_checked_on}</Field>
        <Text size="xs" c="dimmed" mt="xs">
          The universe rules, the daily cycle and reconciliation settings are in the files
          tab, as loaded.
        </Text>
      </Stack>
    </Section>
  );
}

export function ConfigPage() {
  const config = useConfig();
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab");
  const tab: Tab = TABS.find((t) => t === asked) ?? "check";
  const data = config.data;

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Config</Title>
          <Text size="sm" c="dimmed">
            Read-only: edit the files in the workspace's <code>config/</code> folder, then
            Refresh. {config.dataUpdatedAt ? `Read ${dateTime(new Date(config.dataUpdatedAt).toISOString())}.` : ""}
          </Text>
        </div>
        <Group>
          {data && (
            <Badge color={data.valid ? "green" : "red"} size="lg">
              {data.valid ? "check passes" : "check fails"}
            </Badge>
          )}
          <Button
            variant="default"
            leftSection={<IconRefresh size={16} />}
            loading={config.isFetching}
            onClick={() => void config.refetch()}
          >
            Refresh
          </Button>
        </Group>
      </Group>

      {config.isPending && <Loader />}
      {config.isError && <ErrorAlert error={config.error} />}
      {data && (
        <Tabs value={tab} onChange={(value) => value && setParams({ tab: value })}>
          <Tabs.List mb="md">
            <Tabs.Tab value="check">Check</Tabs.Tab>
            <Tabs.Tab value="risk">Risk</Tabs.Tab>
            <Tabs.Tab value="strategies" disabled={!data.valid}>
              Strategies and sweeps
            </Tabs.Tab>
            <Tabs.Tab value="market" disabled={!data.market}>
              Market
            </Tabs.Tab>
            <Tabs.Tab value="files" disabled={data.files.length === 0}>
              Files as loaded
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="check">
            <Check config={data} />
          </Tabs.Panel>
          <Tabs.Panel value="risk">
            <RiskTab guardrails={data.guardrails} profiles={data.profiles} />
          </Tabs.Panel>
          <Tabs.Panel value="strategies">
            <StrategiesTab strategies={data.strategies} cash={data.cash_budget} sweeps={data.sweeps} />
          </Tabs.Panel>
          <Tabs.Panel value="market">{data.market && <Market market={data.market} />}</Tabs.Panel>
          <Tabs.Panel value="files">
            <Text size="sm" c="dimmed" mb="sm">
              Every setting Tyche loaded, by file, exactly as hashed: what a run record
              stores so the run can be reproduced. Comments are not kept.
            </Text>
            <Accordion multiple variant="separated">
              {data.files.map((file) => (
                <Accordion.Item key={file.path} value={file.path}>
                  <Accordion.Control>
                    <code>{file.path}</code>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Settings settings={file.settings} />
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          </Tabs.Panel>
        </Tabs>
      )}
    </Stack>
  );
}
