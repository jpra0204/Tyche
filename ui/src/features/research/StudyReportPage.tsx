// A study's report.html, shown in the console's report frame.
import { Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { Link, useParams } from "react-router";

import { ErrorAlert } from "../../components/ErrorAlert";
import { ReportFrame } from "../../components/ReportFrame";
import { study as studyOf, studyKind } from "./studies";
import { useStudyReport } from "./useResearch";

export function StudyReportPage() {
  const { kind, studyId = "" } = useParams();
  const study = studyOf(studyKind(kind));
  const report = useStudyReport(study.kind, studyId);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={2}>{study.label} report</Title>
          <Text size="sm" c="dimmed" ff="monospace">
            {studyId}
          </Text>
        </div>
        <Button
          component={Link}
          to={`/research?tab=${study.kind}`}
          variant="default"
          leftSection={<IconArrowLeft size={16} />}
        >
          Research
        </Button>
      </Group>
      {report.isPending && <Loader />}
      {report.isError && <ErrorAlert error={report.error} />}
      {report.data !== undefined && (
        <ReportFrame html={report.data} title={`${study.label} report for ${studyId}`} />
      )}
    </Stack>
  );
}
