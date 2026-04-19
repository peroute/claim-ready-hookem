import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Processing your claim · Claim-ready",
};

export default function ProcessingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
