export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
      <h1 className="text-fg text-4xl sm:text-6xl font-semibold tracking-tight max-w-3xl leading-tight">
        Point a camera.{" "}
        <span className="text-accent">Know the card.</span>
      </h1>
      <p className="mt-6 text-fg-dim text-lg max-w-xl">
        A premium Pokémon card grading and valuation platform.
      </p>
    </main>
  );
}