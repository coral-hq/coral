import type { Meta, StoryObj } from "@storybook/react-vite";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { CoralHero } from "./CoralHero";
import { CoralMark } from "./CoralMark";
import { CoralWordmark } from "./CoralWordmark";

const meta = {
  title: "Brand/Coral",
  tags: ["visual-snapshot"],
  decorators: [
    (Story) => (
      <CapabilitiesProvider info={FALLBACK_SERVER_INFO}>
        <div className="flex min-h-40 w-[620px] items-center justify-center rounded-xl border bg-background p-6">
          <Story />
        </div>
      </CapabilitiesProvider>
    ),
  ],
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const Mark: Story = {
  render: () => <CoralMark className="size-24" />,
};

export const WorkingMark: Story = {
  render: () => <CoralMark className="otto-working size-16" />,
};

export const Wordmark: Story = {
  render: () => <CoralWordmark />,
};

export const Hero: Story = {
  render: () => <CoralHero heading="Direct the run…" />,
};

export const HeroWithoutHeading: Story = {
  render: () => <CoralHero heading="" />,
};
