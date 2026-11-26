import { Alert, Button, Group, Loader, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";

import { ErrorAlert } from "../../components/ErrorAlert";
import { LastRun } from "../runs/RunPanel";
import { useCurrentRun } from "../runs/useRun";
import { AccountCard } from "../status/AccountCard";
import { TradingCard } from "../status/TradingCard";
import { useStatus } from "../status/useStatus";
import { AlertsCard } from "./AlertsCard";
import { PaperCycleCard } from "./PaperCycleCard";
import { ReconciliationCard } from "./ReconciliationCard";
import { StopControls } from "./StopControls";
import { usePaper } from "./usePaper";

export function PaperPage() {
  const status = useStatus("default");
  const paper = usePaper();
  const current = useCurrentRun();
  const running = current.data?.state === "running";

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Paper</Title>
          <Text size="sm" c="dimmed">
            The IBKR paper account: the cycle, what stops trading, the account, reconciliation
            and alerts. Live trading is never run from here.
          </Text>
        </div>
        <Button
          variant="default"
          leftSection={<IconRefresh size={16} />}
          loading={status.isFetching || paper.isFetching}
          onClick={() => {
            void status.refetch();
            void paper.refetch();
          }}
        >
          Refresh
        </Button>
      </Group>

      {status.isPending && <Loader />}
      {status.isError && <ErrorAlert error={status.error} />}
      {status.data && (
        <>
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
            <PaperCycleCard status={status.data} running={running} />
            <Stack gap="sm">
              <TradingCard trading={status.data.trading} />
              <StopControls trading={status.data.trading} running={running} />
            </Stack>
          </SimpleGrid>
          <LastRun run={current.data} />
          <AccountCard account={status.data.account ?? null} />
        </>
      )}

      {paper.isError && <ErrorAlert error={paper.error} />}
      {paper.data?.state_unreadable && (
        <Alert color="orange" title="The state database cannot be read">
          {paper.data.state_unreadable}
        </Alert>
      )}
      {paper.data && (
        <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
          <ReconciliationCard found={paper.data.reconciliations} />
          <AlertsCard alerts={paper.data.alerts} />
        </SimpleGrid>
      )}
    </Stack>
  );
}
