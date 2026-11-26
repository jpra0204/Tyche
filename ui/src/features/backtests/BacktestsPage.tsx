import { Button, Loader, Stack, Text, Title } from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";

import { ErrorAlert } from "../../components/ErrorAlert";
import { Section } from "../../components/Section";
import { LastRun } from "../runs/RunPanel";
import { useCurrentRun } from "../runs/useRun";
import { BacktestForm } from "./BacktestForm";
import { BacktestTable } from "./BacktestTable";
import { useBacktests } from "./useBacktests";

export function BacktestsPage() {
  const backtests = useBacktests();
  const current = useCurrentRun();

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Backtests</Title>
        <Text size="sm" c="dimmed">
          The configured strategies on cached history, as <code>tyche backtest</code> runs
          them. Each run is recorded in <code>reports/backtests/</code>.
        </Text>
      </div>

      <BacktestForm />
      <LastRun run={current.data} />

      <Section
        title="Recorded backtests"
        aside={
          <Button
            variant="default"
            size="xs"
            leftSection={<IconRefresh size={14} />}
            loading={backtests.isFetching}
            onClick={() => void backtests.refetch()}
          >
            Refresh
          </Button>
        }
      >
        {backtests.isPending && <Loader />}
        {backtests.isError && <ErrorAlert error={backtests.error} />}
        {backtests.data && <BacktestTable backtests={backtests.data} />}
      </Section>
    </Stack>
  );
}
