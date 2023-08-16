from datetime import datetime, timedelta
import json
import os

import boto3

import verinfast.cloud.aws.regions as r

regions = r.regions


def get_metric_for_instance(
            metric: str,
            instance_id: str,
            namespace: str = 'AWS/EC2',
            unit: str = 'Percent'
        ):
    client = boto3.client('cloudwatch')
    response = client.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric,
        Dimensions=[
            {
                'Name': 'InstanceId',
                'Value': instance_id
            },
        ],
        StartTime=datetime.today() - timedelta(days=90),
        EndTime=datetime.today(),
        Period=60*60,
        Statistics=[
            'Average',
            'Maximum',
            'Minimum'
        ],
        Unit=unit
    )
    return response


def parse_multi(datapoint: dict) -> dict:
    dp_sum = 0
    dp_count = 0
    dp_min = 0
    dp_max = 0

    for entry in datapoint:
        if 'Average' in entry:
            e = entry['Average']
            dp_sum += e
            dp_count += 1
        if 'Minimum' in entry:
            dp_min += entry['Minimum']
        if 'Maximum' in entry:
            dp_max += entry['Maximum']

    return {
        "Timestamp": datapoint["Timestamp"],
        "Minimum": dp_min / dp_count,
        "Average": dp_sum / dp_count,
        "Maximum": dp_max / dp_count
        }


def get_instance_utilization(instance_id: str):
    cpu_resp = get_metric_for_instance(
            metric='CPUUtilization',
            instance_id=instance_id
        )

    mem_resp = get_metric_for_instance(
            metric='mem_used_percent',
            instance_id=instance_id,
            namespace='CWAgent'
        )

    hdd_resp = get_metric_for_instance(
            metric='disk_used_percent',
            instance_id=instance_id,
            namespace='CWAgent'
        )

    cpu_stats = []
    mem_stats = []
    hdd_stats = []

    # each instance may have more than 1 CPU
    for datapoint in cpu_resp['Datapoints']:
        summary = parse_multi(datapoint)
        cpu_stats.append(summary)

    # memory and disk are not collected by default

    # each instance may have more than one disk
    if "Datapoints" in hdd_resp:
        for datapoint in hdd_resp["Datapoints"]:
            summary = parse_multi(datapoint)
            hdd_stats.append(summary)
    # memory
    if "Datapoints" in mem_resp:
        mem_stats = mem_resp["Datapoints"]

    data = []
    for t in zip(cpu_stats, mem_stats, hdd_stats):
        datum = {
            "cpu": t[0],
            "mem": t[1],
            "hdd": t[2]
        }
        data.append(datum)

    return data


def get_instances(sub_id: int, path_to_output: str = "./"):
    session = boto3.Session()
    profiles = session.available_profiles
    right_session = None
    for profile in profiles:
        s2 = boto3.Session(profile_name=profile)
        sts = s2.client('sts')
        id = sts.get_caller_identity()
        if int(id['Account']) == sub_id:
            right_session = s2
            break
    if right_session is None:
        return []
    my_instances = []
    for region in regions:
        try:
            client = right_session.client('ec2', region_name=region)
            paginator = client.get_paginator('describe_instances')
            page_iterator = paginator.paginate()
            for page in page_iterator:
                # print(page)
                reservations = page['Reservations']
                for reservation in reservations:
                    instances = reservation['Instances']
                    for instance in instances:
                        tags = instance['Tags']
                        name = [t['Value'] for t in tags if t['Key'] == 'Name'][0]  # noqa: E501

                        # print(instance)
                        result = {
                            "id": instance["InstanceId"],
                            "name": name,
                            "state": instance["State"]["Name"],
                            "type": instance['InstanceType'],
                            "zone": instance['Placement']['AvailabilityZone'],
                            "region": instance['Placement']['AvailabilityZone'][0:-1],  # noqa: E501
                            "subnet": instance['SubnetId'],
                            "architecture": instance['Architecture'],
                            "vpc": instance['VpcId'],
                        }
                        if "PublicIpAddress" in result:
                            result["publicIp"] = instance['PublicIpAddress']
                        else:
                            result["publicIp"] = 'n/a'
                        ni = instance["NetworkInterfaces"]
                        for interface in ni:
                            if 'Association' in interface:
                                if 'PublicIp' in interface['Association']:
                                    result["publicIp"] = interface['Association']['PublicIp']  # noqa: E501

                        my_instances.append(result)
        except:  # noqa: E722
            pass
    upload = {
                "metadata": {
                    "provider": "aws",
                    "account": str(sub_id)
                },
                "data": my_instances
            }
    aws_output_file = os.path.join(
        path_to_output,
        f'aws-instances-{sub_id}.json'
    )

    with open(aws_output_file, 'w') as outfile:
        outfile.write(json.dumps(upload, indent=4))
    return aws_output_file

# Test Code
# i = get_instances(436708548746)
