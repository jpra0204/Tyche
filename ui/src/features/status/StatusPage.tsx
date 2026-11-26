import { Button, Group, Loader, Select, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { useState } from "react";

import { ErrorAlert } from "../../components/ErrorAlert";
import { AccountCard } from "./AccountCard";
import { ConfigCard } from "./ConfigCard";
import { TradingCard } from "./TradingCard";
import { useStatus } from "./useStatus";

const DEFAULT_PROFILE = "default";

export function StatusPage() {
  const [riskProfile, setRiskProfile] = useState(DEFAULT_PROFILE);
  const status = useStatus(riskProfile);
  const profiles = status.data?.config.risk_profiles ?? [riskProfile];

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Status</Title>
          <Text size="sm" c="dimmed">
            {status.data ? status.data.workspace : "Reading the workspace…"}
          </Text>
        </div>
        <Group align="flex-end">
          <Select
            label="Risk profile"
            data={profiles}
            value={riskProfile}
            onChange={(value) => value && setRiskProfile(value)}
            allowDeselect={false}
            w={180}
          />
          <Button
            variant="default"
            leftSection={<IconRefresh size={16} />}
            loading={status.isFetching}
            onClick={() => void status.refetch()}
          >
            Refresh
          </Button>
        </Group>
      </Group>

      {status.isPending && <Loader />}
      {status.isError && <ErrorAlert error={status.error} />}
      {status.data && (
        <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
          <TradingCard trading={status.data.trading} />
          <ConfigCard config={status.data.config} secrets={status.data.secrets} />
          <AccountCard account={status.data.account ?? null} />
        </SimpleGrid>
      )}
    </Stack>
  );
}
