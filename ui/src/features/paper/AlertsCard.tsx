// The latest alerts, as the logs recorded them, and whether Discord got each one.
import { Badge, Group, List, Stack, Text, Tooltip } from "@mantine/core";

import type { AlertView } from "../../api/types";
import { Section } from "../../components/Section";
import { dateTime } from "../../lib/format";

function Delivery({ alert }: { alert: AlertView }) {
  switch (alert.delivery) {
    case "sent":
      return (
        <Badge size="sm" variant="light" color="green">
          sent
        </Badge>
      );
    case "no_channel":
      return (
        <Tooltip label="DISCORD_WEBHOOK_URL is not set">
          <Badge size="sm" variant="light" color="gray">
            not sent: no channel
          </Badge>
        </Tooltip>
      );
    case "not_sent":
      return (
        <Tooltip label={alert.error ?? ""} multiline w={320}>
          <Badge size="sm" variant="light" color="red">
            not sent
          </Badge>
        </Tooltip>
      );
  }
}

export function AlertsCard({ alerts }: { alerts: AlertView[] }) {
  return (
    <Section title="Alerts">
      {alerts.length === 0 ? (
        <Text size="sm" c="dimmed">
          No alert in the logs yet.
        </Text>
      ) : (
        <Stack gap="md">
          {alerts.map((alert, index) => (
            <div key={`${alert.at}-${index}`}>
              <Group gap="xs" wrap="nowrap">
                <Text size="sm" fw={600}>
                  {alert.title}
                </Text>
                <Delivery alert={alert} />
              </Group>
              <Text size="xs" c="dimmed">
                {dateTime(alert.at)} · {alert.kind}
              </Text>
              {alert.lines.length > 0 && (
                <List size="xs" mt={4}>
                  {alert.lines.map((line, i) => (
                    <List.Item key={i}>{line}</List.Item>
                  ))}
                </List>
              )}
            </div>
          ))}
        </Stack>
      )}
    </Section>
  );
}
