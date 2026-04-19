import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Your claim packet · Claim-ready",
};

export default function PacketLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
