import { Hero } from "./sections/Hero";
import { Problem } from "./sections/Problem";
import { Pipeline } from "./sections/Pipeline";
import { Roadmap } from "./sections/Roadmap";
import { Grading } from "./sections/Grading";
import { Stack } from "./sections/Stack";
import { Footer } from "./sections/Footer";

export default function Home() {
  return (
    <main>
      <Hero />
      <Problem />
      <Pipeline />
      <Roadmap />
      <Grading />
      <Stack />
      <Footer />
    </main>
  );
}