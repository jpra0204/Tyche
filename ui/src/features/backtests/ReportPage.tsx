// A backtest's report.html, shown in the console's report frame.
import { Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { Link, useParams } from "react-router";

import { ErrorAlert } from "../../components/ErrorAlert";
import { ReportFrame } from "../../components/ReportFrame";
import { useBacktestReport } from "./useBacktests";

export function ReportPage() {
  const { runId = "" } = useParams();
  const report = useBacktestReport(runId);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={2}>Backtest report</Title>
          <Text size="sm" c="dimmed" ff="monospace">
            {runId}
          </Text>
        </div>
        <Button
          component={Link}
          to="/backtests"
          variant="default"
          leftSection={<IconArrowLeft size={16} />}
        >
          Backtests
        </Button>
      </Group>
      {report.isPending && <Loader />}
      {report.isError && <ErrorAlert error={report.error} />}
      {report.data !== undefined && <ReportFrame html={report.data} title={`Report for ${runId}`} />}
    </Stack>
  );
}

