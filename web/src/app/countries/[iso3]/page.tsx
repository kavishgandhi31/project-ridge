import { CountryDashboard } from "./country-dashboard";

interface Props {
  params: Promise<{ iso3: string }>;
}

export default async function CountryPage({ params }: Props) {
  const { iso3 } = await params;
  return <CountryDashboard iso3={iso3.toUpperCase()} />;
}
