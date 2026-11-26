// `tyche data fetch` from a form: the market profile's whole list, or chosen symbols.
import {
  Alert,
  Button,
  Group,
  Loader,
  SegmentedControl,
  Select,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { useState } from "react";

import type { FetchRequest } from "../../api/types";
import { ErrorAlert } from "../../components/ErrorAlert";
import { Section } from "../../components/Section";
import { LastRun } from "../runs/RunPanel";
import { useCurrentRun, useStartRun } from "../runs/useRun";
import { useData } from "./useData";

type Mode = "all" | "symbols";

const ASSET_CLASSES = [
  { value: "etf", label: "ETF" },
  { value: "stock", label: "Stock" },
];

export function DataPage() {
  const data = useData();
  const current = useCurrentRun();
  const start = useStartRun();
  const running = current.data?.state === "running";

  const [mode, setMode] = useState<Mode>("all");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [exchange, setExchange] = useState<string | null>(null);
  const [assetClass, setAssetClass] = useState<"etf" | "stock">("etf");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");

  const ready = mode === "all" || (symbols.length > 0 && exchange !== null);

  function fetch() {
    const request: FetchRequest =
      mode === "all"
        ? { command: "data_fetch", every_candidate: true, symbols: [] }
        : {
            command: "data_fetch",
            every_candidate: false,
            symbols,
            exchange,
            asset_class: assetClass,
          };
    start.mutate({ ...request, first: first || null, last: last || null });
  }

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Data</Title>
        <Text size="sm" c="dimmed">
          Daily bars, dividends and splits from Yahoo Finance into the workspace cache, as{" "}
          <code>tyche data fetch</code> does. For personal use only.
        </Text>
      </div>

      {data.isPending && <Loader />}
      {data.isError && <ErrorAlert error={data.error} />}
      {data.data && (
        <Section title="Fetch">
          <Stack gap="md">
            <SegmentedControl
              value={mode}
              onChange={(value) => setMode(value as Mode)}
              data={[
                { value: "all", label: "Everything Tyche follows" },
                { value: "symbols", label: "Chosen symbols" },
              ]}
              w="fit-content"
            />

            {mode === "all" ? (
              data.data.error ? (
                <Alert color="red" title="The configuration cannot be read">
                  {data.data.error}
                </Alert>
              ) : (
                <Text size="sm">
                  The market profile's candidates and its benchmark, exactly what a backtest
                  replays: {data.data.followed.join(", ")}.
                </Text>
              )
            ) : (
              <Group align="flex-start" grow>
                <TagsInput
                  label="Symbols"
                  description="As the exchange lists them: SPY, BRK.B"
                  value={symbols}
                  onChange={(values) => setSymbols(values.map((v) => v.trim().toUpperCase()))}
                  splitChars={[",", " "]}
                  clearable
                />
                <Select
                  label="Exchange"
                  description="Where the symbols are listed"
                  data={data.data.exchanges.map((e) => ({
                    value: e.mic,
                    label: `${e.mic}: ${e.name}`,
                  }))}
                  value={exchange}
                  onChange={setExchange}
                />
                <Select
                  label="Asset class"
                  description=" "
                  data={ASSET_CLASSES}
                  value={assetClass}
                  onChange={(value) => value && setAssetClass(value as "etf" | "stock")}
                  allowDeselect={false}
                />
              </Group>
            )}

            <Group align="flex-start">
              <TextInput
                type="date"
                label="From"
                description={`Defaults to ${data.data.default_first}`}
                value={first}
                onChange={(event) => setFirst(event.currentTarget.value)}
                w={200}
              />
              <TextInput
                type="date"
                label="To"
                description="Defaults to today"
                value={last}
                onChange={(event) => setLast(event.currentTarget.value)}
                w={200}
              />
            </Group>

            <Text size="xs" c="dimmed">
              Only sessions not already cached are downloaded, and a session only once the
              market profile's wait after its close has passed.
            </Text>

            {start.isError && <ErrorAlert error={start.error} />}
            <Group>
              <Button
                leftSection={<IconDownload size={16} />}
                onClick={fetch}
                disabled={!ready || running}
                loading={start.isPending}
              >
                Fetch
              </Button>
              {running && (
                <Text size="sm" c="dimmed">
                  A run is going; the next can start when it ends.
                </Text>
              )}
            </Group>
          </Stack>
        </Section>
      )}

      <LastRun run={current.data} />
    </Stack>
  );
}
