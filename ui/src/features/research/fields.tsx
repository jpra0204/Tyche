// Fields every research form shares: the date range, the risk profile, the run button.
import { Button, Group, Select, Text, TextInput } from "@mantine/core";
import { IconPlayerPlay } from "@tabler/icons-react";
import type { ReactNode } from "react";

import { ErrorAlert } from "../../components/ErrorAlert";
import { useCurrentRun } from "../runs/useRun";
import { useStatus } from "../status/useStatus";

export interface Range {
  first: string;
  last: string;
}

export function RangeFields({
  range,
  onChange,
  firstHelp = "First session to trade",
}: {
  range: Range;
  onChange: (range: Range) => void;
  firstHelp?: string;
}) {
  return (
    <>
      <TextInput
        type="date"
        label="From"
        description={firstHelp}
        value={range.first}
        onChange={(event) => onChange({ ...range, first: event.currentTarget.value })}
        required
        w={220}
      />
      <TextInput
        type="date"
        label="To"
        description="Defaults to the day before the holdout"
        value={range.last}
        onChange={(event) => onChange({ ...range, last: event.currentTarget.value })}
        w={240}
      />
    </>
  );
}

export function useProfiles(): string[] {
  const status = useStatus("default");
  return status.data?.config.risk_profiles ?? ["default"];
}

export function ProfileSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const profiles = useProfiles();
  return (
    <Select
      label="Risk profile"
      description="A file in config/risk/"
      data={profiles}
      value={value}
      onChange={(v) => v && onChange(v)}
      allowDeselect={false}
      w={200}
    />
  );
}

// The button that starts the run, the reason it cannot, and a refused request's error.
export function RunButton({
  label,
  ready,
  onRun,
  pending,
  error,
}: {
  label: ReactNode;
  ready: boolean;
  onRun: () => void;
  pending: boolean;
  error: unknown;
}) {
  const running = useCurrentRun().data?.state === "running";
  return (
    <>
      {error ? <ErrorAlert error={error} /> : null}
      <Group>
        <Button
          leftSection={<IconPlayerPlay size={16} />}
          disabled={!ready || running}
          loading={pending}
          onClick={onRun}
        >
          {label}
        </Button>
        {running && (
          <Text size="sm" c="dimmed">
            A run is going; the next can start when it ends.
          </Text>
        )}
      </Group>
    </>
  );
}

