// `tyche backtest` from a form: the configured strategies on cached history.
import { Button, Group, Select, Stack, Text, TextInput } from "@mantine/core";
import { IconPlayerPlay } from "@tabler/icons-react";
import { useState } from "react";

import { ErrorAlert } from "../../components/ErrorAlert";
import { Section } from "../../components/Section";
import { useCurrentRun, useStartRun } from "../runs/useRun";
import { useStatus } from "../status/useStatus";

const DEFAULT_PROFILE = "default";

export function BacktestForm() {
  const status = useStatus(DEFAULT_PROFILE);
  const current = useCurrentRun();
  const start = useStartRun();
  const running = current.data?.state === "running";

  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [riskProfile, setRiskProfile] = useState(DEFAULT_PROFILE);
  const profiles = status.data?.config.risk_profiles ?? [DEFAULT_PROFILE];

  return (
    <Section title="Run a backtest">
      <Stack gap="md">
        <Group align="flex-start">
          <TextInput
            type="date"
            label="From"
            description="First session to trade"
            value={first}
            onChange={(event) => setFirst(event.currentTarget.value)}
            required
            w={200}
          />
          <TextInput
            type="date"
            label="To"
            description="Defaults to the day before the holdout"
            value={last}
            onChange={(event) => setLast(event.currentTarget.value)}
            w={240}
          />
          <Select
            label="Risk profile"
            description="A file in config/risk/"
            data={profiles}
            value={riskProfile}
            onChange={(value) => value && setRiskProfile(value)}
            allowDeselect={false}
            w={200}
          />
        </Group>

        <Text size="xs" c="dimmed">
          From the cache only: fetch on the Data page first. A range that reaches the holdout
          is refused. Every run is recorded; running many and keeping the best one is
          overfitting, not progress.
        </Text>

        {start.isError && <ErrorAlert error={start.error} />}
        <Group>
          <Button
            leftSection={<IconPlayerPlay size={16} />}
            disabled={!first || running}
            loading={start.isPending}
            onClick={() =>
              start.mutate({
                command: "backtest",
                first,
                last: last || null,
                risk_profile: riskProfile,
              })
            }
          >
            Backtest
          </Button>
          {running && (
            <Text size="sm" c="dimmed">
              A run is going; the next can start when it ends.
            </Text>
          )}
        </Group>
      </Stack>
    </Section>
  );
}
