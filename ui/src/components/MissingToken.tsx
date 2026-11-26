import { Alert, Center, Code, Stack, Text } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";

export function MissingToken() {
  return (
    <Center h="100vh" p="lg">
      <Alert icon={<IconLock />} title="Open the console from its own address" maw={560}>
        <Stack gap="xs">
          <Text size="sm">
            This page needs the key <Code>tyche ui</Code> made when it started. Open the
            address it printed in the terminal (it ends in <Code>#token=…</Code>).
          </Text>
          <Text size="sm" c="dimmed">
            Each launch has a new key, so an old address stops working when the console
            restarts.
          </Text>
        </Stack>
      </Alert>
    </Center>
  );
}
