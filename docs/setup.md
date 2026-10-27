# Deploy, verify, clean up

Everything below creates only Always Free-eligible resources in your home region. You need an OCI tenancy and, for the CLI path, the OCI CLI configured with your credentials. Replace the `<...>` placeholders with real OCIDs/values.

## 1. Create the bucket with object events enabled

The bucket must emit object events or the rule never fires - this is off by default.

Console: Object Storage -> Create Bucket -> name `upload-inbox`, default storage tier, in your compartment, and tick **Emit Object Events**. (On an existing bucket: bucket details -> Edit -> Emit object events.)

CLI:
```
oci os bucket create --name upload-inbox --compartment-id <compartment-ocid> --object-events-enabled true
```

(For an existing bucket: `oci os bucket update --name upload-inbox --object-events-enabled true`.)

One compartment rule: an Events rule only matches events from its own compartment and its child compartments, so create the rule in the same compartment as the bucket.

## 2. Create the Notifications topic and a subscription

Console: Notifications -> Topics -> Create Topic -> name `upload-alerts`.

CLI:
```
oci ons topic create --name upload-alerts --compartment-id <compartment-ocid>
```

Then pick one (or both) delivery paths:

**2a. Email (zero code).** Console: on the topic, Create Subscription -> protocol Email -> your address, then **click Confirm in the email** - the subscription stays Pending until you do. CLI:
```
oci ons subscription create --protocol EMAIL --topic-id <notifications-topic-ocid> --subscription-endpoint <your-email-address>
```

**2b. HTTPS to this repo's receiver (formatted, logged alerts).** Run the receiver somewhere reachable over HTTPS (an Always Free compute VM works):
```
python3 -m receiver.server --port 8080 --auto-confirm
```
Then subscribe its public URL:
```
oci ons subscription create --protocol HTTPS_CUSTOM --topic-id <notifications-topic-ocid> --subscription-endpoint <your-receiver-url>
```
OCI sends a Confirmation message to the receiver; with `--auto-confirm` the receiver visits the SubscribeURL itself, otherwise it prints the URL for you to visit. HTTPS delivery is free up to 1M deliveries/month (Oracle published limit, checked 27 Oct 2026). The receiver does not verify OCI message signatures - see the README's honest limits before exposing it.

## 3. Create the Events rule

Create it in the same compartment as the bucket. Edit `config/events-rule.json`: replace `<compartment-ocid>` and `<notifications-topic-ocid>` with the real values from steps 1-2, then:

```
oci events rule create --from-json file://config/events-rule.json
```

Console equivalent: Observability -> Events Service -> Rules -> Create Rule -> condition: Event Type = Object Storage / Object - Create, attribute `bucketName` = `upload-inbox`; action: Notifications, topic `upload-alerts`.

## 4. Verify

Upload any file to the bucket:

```
oci os object put --bucket-name upload-inbox --file ./README.md
```

Within about a minute you should get the alert: an email from the `upload-alerts` topic (path 2a), or a formatted `ALERT [...] createobject: README.md in bucket upload-inbox` line in the receiver log (path 2b). Events are at-least-once, so a rare duplicate is possible. If nothing arrives: check the bucket has Emit Object Events on (step 1), the subscription is Confirmed not Pending (step 2), and the rule's compartment matches the bucket's (step 3).

## 5. Clean up (removes everything)

```
oci events rule delete --rule-id <rule-ocid> --force
oci ons subscription delete --subscription-id <subscription-ocid>
oci ons topic delete --topic-id <notifications-topic-ocid>
oci os object delete --bucket-name upload-inbox --object-name README.md --force
oci os bucket delete --bucket-name upload-inbox --empty
```

(Delete every object before `--empty` works.)

## Optional next steps

- Add an HTTPS or Slack subscription to the same topic - 1M HTTPS deliveries/month are free.
- Add a Monitoring alarm on the `oci_objectstorage` namespace metrics for the bucket; Monitoring is Always Free.
- Manage the same resources as Terraform via Resource Manager (Always Free).
