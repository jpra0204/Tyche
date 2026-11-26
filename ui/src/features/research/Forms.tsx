// One form per study, each running its `tyche` command with the options chosen. An
// option left empty is left out, so the command's own default applies.
import {
  Alert,
  Checkbox,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
} from "@mantine/core";
import { useState } from "react";

import type { ResearchView } from "../../api/types";
import { useStartRun } from "../runs/useRun";
import { ProfileSelect, RangeFields, RunButton, useProfiles, type Range } from "./fields";

const EMPTY: Range = { first: "", last: "" };

function Caution({ children }: { children: React.ReactNode }) {
  return (
    <Text size="xs" c="dimmed">
      {children}
    </Text>
  );
}

export function WalkForwardForm({ research }: { research: ResearchView }) {
  const start = useStartRun();
  const [range, setRange] = useState(EMPTY);
  const [trainYears, setTrainYears] = useState<number | string>(5);
  const [testYears, setTestYears] = useState<number | string>(1);
  const [rolling, setRolling] = useState(false);
  const [sweep, setSweep] = useState<string | null>(null);
  const [riskProfile, setRiskProfile] = useState("default");

  return (
    <Stack gap="md">
      <Group align="flex-start">
        <RangeFields
          range={range}
          onChange={setRange}
          firstHelp="First day of the first training window"
        />
        <ProfileSelect value={riskProfile} onChange={setRiskProfile} />
      </Group>
      <Group align="flex-end">
        <NumberInput
          label="Training years"
          description="In the first window"
          value={trainYears}
          onChange={setTrainYears}
          min={1}
          max={30}
          allowDecimal={false}
          w={160}
        />
        <NumberInput
          label="Test years"
          description="In each window"
          value={testYears}
          onChange={setTestYears}
          min={1}
          max={10}
          allowDecimal={false}
          w={160}
        />
        <Switch
          label="Rolling: keep every training window this long"
          checked={rolling}
          onChange={(event) => setRolling(event.currentTarget.checked)}
          mb={8}
        />
      </Group>
      <Select
        label="Sweep on each training window"
        description="Optional: each training window picks the parameters its test window runs"
        placeholder="None: keep the configured parameters"
        data={research.sweeps}
        value={sweep}
        onChange={setSweep}
        clearable
        w={420}
      />
      <Caution>
        Folds of whole calendar years, each a backtest on cached history; the test windows,
        joined, are the out-of-sample result. A range that reaches the holdout is refused.
      </Caution>
      <RunButton
        label="Walk forward"
        ready={range.first !== "" && trainYears !== "" && testYears !== ""}
        pending={start.isPending}
        error={start.error}
        onRun={() =>
          start.mutate({
            command: "walk_forward",
            first: range.first,
            last: range.last || null,
            train_years: Number(trainYears),
            test_years: Number(testYears),
            rolling,
            sweep,
            risk_profile: riskProfile,
          })
        }
      />
    </Stack>
  );
}

export function SweepForm({ research }: { research: ResearchView }) {
  const start = useStartRun();
  const [range, setRange] = useState(EMPTY);
  const [name, setName] = useState<string | null>(research.sweeps[0] ?? null);
  const [riskProfile, setRiskProfile] = useState("default");

  return (
    <Stack gap="md">
      {research.sweeps.length === 0 && (
        <Alert color="orange" title="No sweep in config/sweeps/">
          Add one to the workspace (see the parameter sweeps guide), then refresh.
        </Alert>
      )}
      <Group align="flex-start">
        <Select
          label="Sweep"
          description="config/sweeps/<name>.toml"
          data={research.sweeps}
          value={name}
          onChange={setName}
          allowDeselect={false}
          w={220}
        />
        <RangeFields range={range} onChange={setRange} />
        <ProfileSelect value={riskProfile} onChange={setRiskProfile} />
      </Group>
      <Caution>
        Every combination is a backtest over the same days, and every one counts as a trial
        that deflates every later Sharpe ratio of the plugin. The pick is in-sample: for an
        out-of-sample result, walk forward with this sweep.
      </Caution>
      <RunButton
        label="Sweep"
        ready={range.first !== "" && name !== null}
        pending={start.isPending}
        error={start.error}
        onRun={() =>
          name &&
          start.mutate({
            command: "sweep",
            name,
            first: range.first,
            last: range.last || null,
            risk_profile: riskProfile,
          })
        }
      />
    </Stack>
  );
}

export function CapitalForm({ research }: { research: ResearchView }) {
  const start = useStartRun();
  const defaults = research.capital;
  const [range, setRange] = useState(EMPTY);
  const [amounts, setAmounts] = useState<string[]>([]);
  const [reference, setReference] = useState("");
  const [tolerance, setTolerance] = useState("");
  const [positions, setPositions] = useState<number | string>("");
  const [riskProfile, setRiskProfile] = useState("default");

  return (
    <Stack gap="md">
      <Group align="flex-start">
        <RangeFields range={range} onChange={setRange} />
        <ProfileSelect value={riskProfile} onChange={setRiskProfile} />
      </Group>
      <Group align="flex-start">
        <TagsInput
          label="Amounts"
          description={`Starting cash to test, smallest first. Default ${defaults.amounts.join(", ")}`}
          placeholder="Default"
          value={amounts}
          onChange={(values) => setAmounts(values.map((v) => v.trim().replaceAll(",", "")))}
          splitChars={[" ", ";"]}
          w={420}
        />
        <TextInput
          label="Reference"
          description={`The large account. Default ${defaults.reference}`}
          placeholder="Default"
          value={reference}
          onChange={(event) => setReference(event.currentTarget.value.trim())}
          w={200}
        />
        <TextInput
          label="Tolerance"
          description={`CAGR points a year. Default ${Number(defaults.tolerance)}`}
          placeholder="Default"
          value={tolerance}
          onChange={(event) => setTolerance(event.currentTarget.value.trim())}
          w={200}
        />
        <NumberInput
          label="Positions"
          description={`For the round-trip arithmetic. Default ${defaults.positions}`}
          placeholder="Default"
          value={positions}
          onChange={setPositions}
          min={1}
          max={50}
          allowDecimal={false}
          w={200}
        />
      </Group>
      <Caution>
        Each strategy runs alone with the whole account, at every amount and on the
        reference account, under IBKR Fixed and Tiered. In the profile's currency.
      </Caution>
      <RunButton
        label="Find the minimum capital"
        ready={range.first !== ""}
        pending={start.isPending}
        error={start.error}
        onRun={() =>
          start.mutate({
            command: "capital",
            first: range.first,
            last: range.last || null,
            amounts,
            reference: reference || null,
            tolerance: tolerance || null,
            positions: positions === "" ? null : Number(positions),
            risk_profile: riskProfile,
          })
        }
      />
    </Stack>
  );
}

export function ProfilesForm() {
  const start = useStartRun();
  const profiles = useProfiles();
  const [range, setRange] = useState(EMPTY);
  const [chosen, setChosen] = useState<string[]>([]);
  const [every, setEvery] = useState(true);

  return (
    <Stack gap="md">
      <Group align="flex-start">
        <RangeFields range={range} onChange={setRange} />
      </Group>
      <Group align="flex-end">
        <Checkbox
          label="Every profile in config/risk/"
          checked={every}
          onChange={(event) => setEvery(event.currentTarget.checked)}
          mb={8}
        />
        {!every && (
          <MultiSelect
            label="Profiles"
            data={profiles}
            value={chosen}
            onChange={setChosen}
            w={420}
          />
        )}
      </Group>
      <Caution>
        One backtest per profile over the same days, with the same strategies. It names no
        best profile and adds no trial; choosing a profile by these in-sample results is a
        selection too.
      </Caution>
      <RunButton
        label="Compare"
        ready={range.first !== "" && (every || chosen.length > 0)}
        pending={start.isPending}
        error={start.error}
        onRun={() =>
          start.mutate({
            command: "compare_profiles",
            first: range.first,
            last: range.last || null,
            risk_profiles: every ? [] : chosen,
          })
        }
      />
    </Stack>
  );
}
