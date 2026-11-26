import { Card, Group, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

export function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="sm">
        <Title order={4}>{title}</Title>
        {aside}
      </Group>
      {children}
    </Card>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Group gap="xs" wrap="nowrap" align="baseline">
      <Text size="sm" c="dimmed" w={140} style={{ flexShrink: 0 }}>
        {label}
      </Text>
      <Text size="sm" component="div">
        {children}
      </Text>
    </Group>
  );
}
