import type { Metadata } from "next";
import { FileCheck, Shield, Zap } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { UploadCard } from "@/components/upload/upload-card";

export const metadata: Metadata = {
  title: "Claim-ready — Turn your damage video into a claim packet",
};

const FEATURES = [
  {
    icon: Zap,
    title: "Fast processing",
    body: "Complete claim documentation in minutes, not hours.",
  },
  {
    icon: FileCheck,
    title: "Policy-aligned",
    body: "Automatic coverage matching with relevant citations.",
  },
  {
    icon: Shield,
    title: "Professional output",
    body: "FNOL letter and itemized inventory ready for submission.",
  },
];

export default function LandingPage() {
  return (
    <main className="container py-16 md:py-24">
      <div className="grid gap-12 md:gap-16 lg:grid-cols-[1.1fr_1fr] lg:gap-20">
        {/* LEFT — pitch column */}
        <section className="flex flex-col">
          <Logo />

          <h1 className="mt-10 text-balance text-5xl font-extrabold leading-[1.05] tracking-tight text-slate-900 md:text-6xl">
            Turn your damage video into a claim packet.
          </h1>

          <p className="mt-6 max-w-xl text-xl leading-relaxed text-slate-600">
            AI-generated inventory, policy citations, and an FNOL letter ready
            to send — in under 3 minutes.
          </p>

          <ul className="mt-12 space-y-6">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex items-start gap-4">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-navy-50 text-navy-600 ring-1 ring-inset ring-navy-100">
                  <Icon className="h-5 w-5" strokeWidth={2.25} />
                </span>
                <div>
                  <p className="font-semibold text-slate-900">{title}</p>
                  <p className="mt-0.5 text-slate-600">{body}</p>
                </div>
              </li>
            ))}
          </ul>

          <p className="mt-16 text-sm text-slate-500">
            Built at Hook &lsquo;Em Hacks 2026. Powered by Gemini 2.5 and CLIP.
          </p>
        </section>

        {/* RIGHT — intake + dropzones + submit */}
        <section className="flex">
          <UploadCard />
        </section>
      </div>
    </main>
  );
}
