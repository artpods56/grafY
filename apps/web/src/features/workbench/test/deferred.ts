export interface Deferred<Value> {
  promise: Promise<Value>;
  resolve: (value: Value | PromiseLike<Value>) => void;
  reject: (reason?: unknown) => void;
}

export function deferred<Value>(): Deferred<Value> {
  let resolve!: Deferred<Value>["resolve"];
  let reject!: Deferred<Value>["reject"];
  const promise = new Promise<Value>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}
