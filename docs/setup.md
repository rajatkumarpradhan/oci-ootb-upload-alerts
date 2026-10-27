# Deploy, verify, clean up

Everything below creates only Always Free-eligible resources in your home region. You need an OCI tenancy and, for the CLI path, the OCI CLI configured with your credentials. Replace the `<...>` placeholders with real OCIDs/values.

## 1. Create the bucket

Console: Object Storage -> Create Bucket -> name `upload-inbox`, default storage tier, in your compartment.

CLI:
```
oci os bucket create --name upload-inbox --compartment-id <compartment-ocid>
```

## 2. Create the Notifications topic and email subscription

Console: Notifications -> Topics -> Create Topic -> name `upload-alerts`. Then on the topic: Create Subscription -> protocol Email -> your address. **Check your inbox and click Confirm** - the subscription stays Pending until you do, and no alerts flow before that.

CLI:
```
oci ons topic create --name upload-alerts --compartment-id <compartment-ocid>
oci ons subscription create --protocol EMAIL --topic-id <notifications-topic-ocid> --subscription-endpoint <your-email-address>
```

## 3. Create the Events rule

Edit `config/events-rule.json`: replace `<compartment-ocid>` and `<notifications-topic-ocid>` with the real values from steps 1-2, then:

```
oci events rule create --from-json file://config/events-rule.json
```

Console equivalent: Observability -> Events Service -> Rules -> Create Rule -> condition: Event Type = Object Storage / Object - Create, attribute `bucketName` = `upload-inbox`; action: Notifications, topic `upload-alerts`.

## 4. Verify

Upload any file to the bucket:

```
oci os object put --bucket-name upload-inbox --file ./README.md
```

Within about a minute you should get an email from the `upload-alerts` topic with the event details (bucket, object name, time). Events are at-least-once, so a rare duplicate is possible.

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
