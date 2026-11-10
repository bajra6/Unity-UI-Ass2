using System;

[Serializable]
public class DogAction
{
    public string action = "wait";
    public float amount = 0.5f;
    public string reason = "";
    public string source = "";
    public string fallback_error = "";
}

[Serializable]
public class DogObservation
{
    public string session_id;
    public string command;
    public string image_base64;
    public string last_result;
    public bool holding_ball;
    public int step;
}

[Serializable]
public class BridgeHealth
{
    public string status;
    public string model;
    public string provider;
    public bool key_configured;
    public string mode;
    public bool fallback_enabled;
}
