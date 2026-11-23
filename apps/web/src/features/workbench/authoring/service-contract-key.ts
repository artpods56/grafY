/**
 * A service contract as the catalog names it: id and version. Port wiring
 * compares this string the way artifact plugs compare {@link artifactTypeKey}.
 */
export interface ServiceContractIdentity {
  id: string;
  version: number;
}

/** `ocr.document@1`. */
export type ServiceContractId = `${string}@${number}`;

export function serviceContractKey(
  contract: ServiceContractIdentity,
): ServiceContractId {
  return `${contract.id}@${contract.version}`;
}
