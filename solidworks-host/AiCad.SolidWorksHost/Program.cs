using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace AiCad.SolidWorksHost
{
    [DataContract]
    internal sealed class HostPlan
    {
        [DataMember] public string protocol;
        [DataMember] public string source_sha256;
        [DataMember] public string part_name;
        [DataMember] public string units;
        [DataMember] public double tolerance_mm;
        [DataMember] public string template_path;
        [DataMember] public string output_sldprt;
        [DataMember] public string output_step;
        [DataMember] public List<FeaturePlan> features;
    }

    [DataContract]
    internal sealed class FeaturePlan
    {
        [DataMember] public string id;
        [DataMember] public string type;
        [DataMember] public string purpose;
        [DataMember] public string reasoning;
        [DataMember] public List<string> depends_on;
        [DataMember] public string support_feature;
        [DataMember] public double support_top_z_mm;
        [DataMember] public double resulting_top_z_mm;
        [DataMember] public double depth_mm;
        [DataMember] public string end_condition;
        [DataMember] public ProfilePlan profile;
        [DataMember] public ExpectedState expected;
    }

    [DataContract]
    internal sealed class ProfilePlan
    {
        [DataMember] public string kind;
        [DataMember] public double center_x_mm;
        [DataMember] public double center_y_mm;
        [DataMember] public double? width_mm;
        [DataMember] public double? height_mm;
        [DataMember] public double? radius_mm;
        [DataMember] public int? count;
        [DataMember] public double? bolt_circle_radius_mm;
        [DataMember] public double? start_angle_deg;
        [DataMember] public List<CirclePlan> circles;
    }

    [DataContract]
    internal sealed class CirclePlan
    {
        [DataMember] public double x_mm;
        [DataMember] public double y_mm;
        [DataMember] public double radius_mm;
    }

    [DataContract]
    internal sealed class ExpectedState
    {
        [DataMember] public double volume_before_mm3;
        [DataMember] public double volume_after_mm3;
        [DataMember] public double volume_delta_mm3;
        [DataMember] public double[] bbox_mm;
        [DataMember] public int solid_body_count;
    }

    [DataContract]
    internal sealed class ModelSnapshot
    {
        [DataMember] public int solid_body_count;
        [DataMember] public int body_fault_count;
        [DataMember] public double volume_mm3;
        [DataMember] public double surface_area_mm2;
        [DataMember] public double[] bbox_mm;
    }

    [DataContract]
    internal sealed class NativeTopologyReference
    {
        [DataMember] public string reference_key;
        [DataMember] public string semantic_geometry_type;
        [DataMember] public string native_object_type;
        [DataMember] public string classification;
        [DataMember] public string persistent_reference_base64;
        [DataMember] public int persistent_reference_status;
        [DataMember] public bool persistent_reference_resolved;
        [DataMember] public bool required;
        [DataMember] public double[] signature_mm;
        [DataMember] public string custom_property_name;
    }

    [DataContract]
    internal sealed class FeatureReport
    {
        [DataMember] public string id;
        [DataMember] public string type;
        [DataMember] public string purpose;
        [DataMember] public string support_feature;
        [DataMember] public string support_face_selection_method;
        [DataMember] public double? selected_support_plane_z_mm;
        [DataMember] public string sketch_name;
        [DataMember] public int sketch_autodim_status;
        [DataMember] public int sketch_constraint_status;
        [DataMember] public int profile_segment_count;
        [DataMember] public int explicit_radius_dimension_count;
        [DataMember] public int explicit_center_dimension_count;
        [DataMember] public int explicit_center_relation_count;
        [DataMember] public int explicit_rectangle_size_dimension_count;
        [DataMember] public int explicit_rectangle_position_dimension_count;
        [DataMember] public int explicit_rectangle_position_relation_count;
        [DataMember] public bool used_fixed_fallback;
        [DataMember] public int feature_error_code;
        [DataMember] public bool feature_warning;
        [DataMember] public string persistent_reference_base64;
        [DataMember] public int persistent_reference_status;
        [DataMember] public bool persistent_reference_resolved;
        [DataMember] public List<NativeTopologyReference> native_topology = new List<NativeTopologyReference>();
        [DataMember] public ModelSnapshot before;
        [DataMember] public ModelSnapshot after;
        [DataMember] public double expected_volume_after_mm3;
        [DataMember] public double actual_volume_delta_mm3;
        [DataMember] public bool passed;
        [DataMember] public List<string> checks;
    }

    [DataContract]
    internal sealed class HostReport
    {
        [DataMember] public string protocol;
        [DataMember] public string status;
        [DataMember] public string source_sha256;
        [DataMember] public string solidworks_revision;
        [DataMember] public string output_sldprt;
        [DataMember] public string output_step;
        [DataMember] public int sldprt_save_errors;
        [DataMember] public int sldprt_save_warnings;
        [DataMember] public int step_save_errors;
        [DataMember] public int step_save_warnings;
        [DataMember] public List<FeatureReport> features = new List<FeatureReport>();
        [DataMember] public int native_topology_reference_count;
        [DataMember] public int required_native_topology_reference_count;
        [DataMember] public int unresolved_required_native_topology_reference_count;
        [DataMember] public ModelSnapshot final_state;
        [DataMember] public List<string> errors = new List<string>();
    }

    [DataContract]
    internal sealed class ReopenReport
    {
        [DataMember] public string protocol;
        [DataMember] public string status;
        [DataMember] public string solidworks_revision;
        [DataMember] public string input_sldprt;
        [DataMember] public int open_errors;
        [DataMember] public int open_warnings;
        [DataMember] public int aicad_feature_count;
        [DataMember] public List<string> aicad_feature_names = new List<string>();
        [DataMember] public List<string> feature_errors = new List<string>();
        [DataMember] public int native_topology_reference_count;
        [DataMember] public int required_native_topology_reference_count;
        [DataMember] public int unresolved_required_native_topology_reference_count;
        [DataMember] public List<NativeTopologyReference> native_topology = new List<NativeTopologyReference>();
        [DataMember] public ModelSnapshot final_state;
        [DataMember] public List<string> errors = new List<string>();
    }

    internal static class Program
    {
        private const double MillimetersPerMeter = 1000.0;
        private const double CubicMillimetersPerCubicMeter = 1_000_000_000.0;
        private const double SquareMillimetersPerSquareMeter = 1_000_000.0;

        [STAThread]
        private static int Main(string[] args)
        {
            Console.OutputEncoding = new UTF8Encoding(false);
            if (args.Length == 3 && args[0] == "--inspect")
            {
                return InspectSavedPart(Path.GetFullPath(args[1]), Path.GetFullPath(args[2]));
            }
            if (args.Length != 2)
            {
                Console.Error.WriteLine("Usage: AiCad.SolidWorksHost.exe <plan.swplan.json> <report.json> | --inspect <part.SLDPRT> <reopen-report.json>");
                return 2;
            }

            string planPath = Path.GetFullPath(args[0]);
            string reportPath = Path.GetFullPath(args[1]);
            HostReport report = new HostReport { protocol = "AICAD_SOLIDWORKS_REPORT_2", status = "failed" };
            SldWorks app = null;
            ModelDoc2 model = null;
            bool createdApplication = false;
            try
            {
                HostPlan plan = ReadJson<HostPlan>(planPath);
                ValidateEnvelope(plan);
                report.source_sha256 = plan.source_sha256;
                report.output_sldprt = plan.output_sldprt;
                report.output_step = plan.output_step;
                Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
                Directory.CreateDirectory(Path.GetDirectoryName(plan.output_sldprt));
                Directory.CreateDirectory(Path.GetDirectoryName(plan.output_step));
                File.Delete(plan.output_sldprt);
                File.Delete(plan.output_step);

                app = AttachOrStart(out createdApplication);
                report.solidworks_revision = app.RevisionNumber();
                app.CommandInProgress = true;
                model = (ModelDoc2)app.NewDocument(plan.template_path, 0, 0.0, 0.0);
                if (model == null)
                {
                    throw new InvalidOperationException("SolidWorks could not create a part from the configured template.");
                }
                model.ShowFeatureErrorDialog = false;

                var features = new Dictionary<string, Feature>(StringComparer.Ordinal);
                foreach (FeaturePlan featurePlan in plan.features)
                {
                    FeatureReport featureReport = ExecuteFeature(app, model, plan, featurePlan, features);
                    report.features.Add(featureReport);
                    if (!featureReport.passed)
                    {
                        throw new InvalidOperationException("Feature transaction failed: " + featurePlan.id + " :: " + string.Join("; ", featureReport.checks));
                    }
                }

                report.final_state = CaptureSnapshot(model);
                PersistNativeTopologyCatalog(model, report);
                SaveOutputs(app, model, plan, report);
                if (!File.Exists(plan.output_sldprt) || new FileInfo(plan.output_sldprt).Length == 0)
                {
                    throw new InvalidOperationException("SLDPRT output was not created.");
                }
                if (!File.Exists(plan.output_step) || new FileInfo(plan.output_step).Length == 0)
                {
                    throw new InvalidOperationException("STEP output was not created.");
                }
                report.status = "passed";
                WriteJson(reportPath, report);
                Console.WriteLine(reportPath);
                return 0;
            }
            catch (Exception exception)
            {
                report.errors.Add(exception.ToString());
                WriteJson(reportPath, report);
                Console.Error.WriteLine(exception.Message);
                return 1;
            }
            finally
            {
                try
                {
                    if (model != null && app != null)
                    {
                        app.CloseDoc(model.GetTitle());
                    }
                    if (app != null)
                    {
                        app.CommandInProgress = false;
                        if (createdApplication)
                        {
                            app.ExitApp();
                        }
                    }
                }
                catch
                {
                    // Cleanup must not hide the original result.
                }
                ReleaseCom(model);
                ReleaseCom(app);
            }
        }

        private static int InspectSavedPart(string partPath, string reportPath)
        {
            var report = new ReopenReport
            {
                protocol = "AICAD_SOLIDWORKS_REOPEN_REPORT_2",
                status = "failed",
                input_sldprt = partPath,
            };
            SldWorks app = null;
            ModelDoc2 model = null;
            bool createdApplication = false;
            try
            {
                if (!File.Exists(partPath)) throw new FileNotFoundException("SLDPRT input does not exist.", partPath);
                Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
                app = AttachOrStart(out createdApplication);
                report.solidworks_revision = app.RevisionNumber();
                app.CommandInProgress = true;
                int openErrors = 0, openWarnings = 0;
                model = (ModelDoc2)app.OpenDoc6(
                    partPath, (int)swDocumentTypes_e.swDocPART, (int)swOpenDocOptions_e.swOpenDocOptions_Silent,
                    "", ref openErrors, ref openWarnings);
                report.open_errors = openErrors;
                report.open_warnings = openWarnings;
                if (model == null || openErrors != 0)
                    throw new InvalidOperationException("SolidWorks could not reopen the saved part; error=" + openErrors);
                model.ShowFeatureErrorDialog = false;
                model.ForceRebuild3(false);
                Feature current = (Feature)model.FirstFeature();
                while (current != null)
                {
                    string name = current.Name;
                    if (!string.IsNullOrEmpty(name) && name.StartsWith("AICAD_", StringComparison.Ordinal))
                    {
                        report.aicad_feature_names.Add(name);
                        int code = current.GetErrorCode2(out bool warning);
                        if (code != 0 || warning)
                            report.feature_errors.Add(name + ":error=" + code + ",warning=" + warning);
                    }
                    current = (Feature)current.GetNextFeature();
                }
                report.aicad_feature_count = report.aicad_feature_names.Count;
                ReadAndResolveNativeTopologyCatalog(model, report);
                report.final_state = CaptureSnapshot(model);
                if (report.aicad_feature_count == 0) throw new InvalidOperationException("Saved part contains no AICAD features.");
                if (report.feature_errors.Count != 0) throw new InvalidOperationException("Saved part contains feature errors after reopen.");
                if (report.native_topology_reference_count == 0)
                    throw new InvalidOperationException("Saved part contains no AICAD native topology references.");
                if (report.unresolved_required_native_topology_reference_count != 0)
                    throw new InvalidOperationException("Saved part contains unresolved required AICAD native topology references.");
                if (report.final_state.solid_body_count != 1 || report.final_state.body_fault_count != 0)
                    throw new InvalidOperationException("Saved part body is invalid after reopen.");
                report.status = "passed";
                WriteJson(reportPath, report);
                Console.WriteLine(reportPath);
                return 0;
            }
            catch (Exception exception)
            {
                report.errors.Add(exception.ToString());
                WriteJson(reportPath, report);
                Console.Error.WriteLine(exception.Message);
                return 1;
            }
            finally
            {
                try
                {
                    if (model != null && app != null) app.CloseDoc(model.GetTitle());
                    if (app != null)
                    {
                        app.CommandInProgress = false;
                        if (createdApplication) app.ExitApp();
                    }
                }
                catch { }
                ReleaseCom(model);
                ReleaseCom(app);
            }
        }

        private static void ValidateEnvelope(HostPlan plan)
        {
            if (plan == null || plan.protocol != "AICAD_SOLIDWORKS_1")
            {
                throw new InvalidDataException("Unsupported SolidWorks execution protocol.");
            }
            if (plan.units != "mm" || plan.features == null || plan.features.Count == 0)
            {
                throw new InvalidDataException("SolidWorks plan must use mm and contain features.");
            }
            if (!File.Exists(plan.template_path))
            {
                throw new FileNotFoundException("SolidWorks part template was not found.", plan.template_path);
            }
        }

        private static SldWorks AttachOrStart(out bool created)
        {
            try
            {
                created = false;
                return (SldWorks)Marshal.GetActiveObject("SldWorks.Application");
            }
            catch (COMException)
            {
                Type type = Type.GetTypeFromProgID("SldWorks.Application", true);
                created = true;
                var app = (SldWorks)Activator.CreateInstance(type);
                app.Visible = false;
                app.UserControl = false;
                return app;
            }
        }

        private static FeatureReport ExecuteFeature(SldWorks app, ModelDoc2 model, HostPlan plan, FeaturePlan featurePlan, IDictionary<string, Feature> features)
        {
            var report = new FeatureReport
            {
                id = featurePlan.id,
                type = featurePlan.type,
                purpose = featurePlan.purpose,
                support_feature = featurePlan.support_feature,
                checks = new List<string>(),
                before = CaptureSnapshot(model),
                expected_volume_after_mm3 = featurePlan.expected.volume_after_mm3,
            };
            ValidateExpectedBefore(featurePlan, report.before, plan.tolerance_mm, report.checks);

            Face2 supportFace = null;
            if (featurePlan.type == "base_extrude")
            {
                Feature plane = FirstReferencePlane(model);
                if (plane == null || !plane.Select2(false, 0))
                {
                    throw new InvalidOperationException(featurePlan.id + " could not select the first principal plane.");
                }
            }
            else
            {
                supportFace = SelectPlanarSupportFace(model, featurePlan, features, out double selectedSupportPlaneZMm);
                report.support_face_selection_method = "named_feature_exact_z";
                report.selected_support_plane_z_mm = selectedSupportPlaneZMm;
                byte[] reference = (byte[])model.Extension.GetPersistReference3(supportFace);
                report.persistent_reference_base64 = Convert.ToBase64String(reference);
                object resolved = model.Extension.GetObjectByPersistReference3(reference, out int persistStatus);
                report.persistent_reference_status = persistStatus;
                report.persistent_reference_resolved = resolved != null && persistStatus == 0;
                ReleaseCom(resolved);
                if (!report.persistent_reference_resolved)
                {
                    throw new InvalidOperationException(featurePlan.id + " persistent support-face reference did not resolve.");
                }
            }

            SketchManager sketchManager = model.SketchManager;
            sketchManager.InsertSketch(true);
            Sketch sketch = sketchManager.ActiveSketch;
            if (sketch == null)
            {
                throw new InvalidOperationException(featurePlan.id + " did not enter sketch edit mode.");
            }
            SketchPoint datumPoint = sketchManager.CreatePoint(0.0, 0.0, 0.0);
            if (datumPoint == null)
            {
                throw new InvalidOperationException(featurePlan.id + " could not create its sketch datum point.");
            }
            model.ClearSelection2(true);
            datumPoint.Select4(false, null);
            model.SketchAddConstraints("sgFIXED");
            model.ClearSelection2(true);
            bool originalAddToDb = sketchManager.AddToDB;
            bool originalDisplayWhenAdded = sketchManager.DisplayWhenAdded;
            List<SketchSegment> profileSegments = null;
            try
            {
                // Direct database creation prevents support-face inferencing, snapping,
                // and automatic relations from changing the frozen numeric profile.
                sketchManager.AddToDB = true;
                sketchManager.DisplayWhenAdded = false;
                profileSegments = CreateProfile(app, sketch, sketchManager, featurePlan.profile, featurePlan.support_top_z_mm);
            }
            finally
            {
                sketchManager.DisplayWhenAdded = originalDisplayWhenAdded;
                sketchManager.AddToDB = originalAddToDb;
                model.GraphicsRedraw2();
            }
            report.profile_segment_count = profileSegments == null ? 0 : profileSegments.Count;
            AddExplicitRectangleConstraints(
                app, model, sketch, datumPoint, featurePlan.profile, featurePlan.support_top_z_mm, profileSegments,
                out report.explicit_rectangle_size_dimension_count,
                out report.explicit_rectangle_position_dimension_count,
                out report.explicit_rectangle_position_relation_count);
            AddExplicitCircleConstraints(
                app, model, sketch, datumPoint, featurePlan.profile, featurePlan.support_top_z_mm, profileSegments,
                out report.explicit_radius_dimension_count,
                out report.explicit_center_dimension_count,
                out report.explicit_center_relation_count);
            report.sketch_autodim_status = sketchManager.FullyDefineSketch(
                true, true,
                (int)swSketchFullyDefineRelationType_e.swSketchFullyDefineRelationType_Horizontal |
                (int)swSketchFullyDefineRelationType_e.swSketchFullyDefineRelationType_Vertical,
                true,
                (int)swAutodimScheme_e.swAutodimSchemeBaseline, datumPoint,
                (int)swAutodimScheme_e.swAutodimSchemeBaseline, datumPoint,
                (int)swAutodimHorizontalPlacement_e.swAutodimHorizontalPlacementAbove,
                (int)swAutodimVerticalPlacement_e.swAutodimVerticalPlacementRight);
            report.sketch_constraint_status = sketch.GetConstrainedStatus();
            if (report.sketch_constraint_status != (int)swConstrainedStatus_e.swFullyConstrained)
            {
                throw new InvalidOperationException(
                    featurePlan.id + " sketch is not fully constrained; status=" + report.sketch_constraint_status + "; " +
                    SketchConstraintDiagnostics(sketch, profileSegments));
            }
            Feature sketchFeature = (Feature)sketch;
            sketchFeature.Name = "AICAD_SKETCH_" + featurePlan.id;
            report.sketch_name = sketchFeature.Name;
            CaptureSketchTopology(model, featurePlan, profileSegments, report.native_topology);
            sketchManager.InsertSketch(true);
            model.ClearSelection2(true);
            sketchFeature.Select2(false, 0);

            double depthMeters = featurePlan.depth_mm / MillimetersPerMeter;
            Feature feature;
            if (featurePlan.type == "cut_extrude")
            {
                int endCondition = featurePlan.end_condition == "through_all" ? (int)swEndConditions_e.swEndCondThroughAll : (int)swEndConditions_e.swEndCondBlind;
                feature = model.FeatureManager.FeatureCut4(
                    true, false, false, endCondition, (int)swEndConditions_e.swEndCondBlind,
                    depthMeters, 0.0, false, false, false, false, 0.0, 0.0,
                    false, false, false, false, false, true, true,
                    false, false, false, (int)swStartConditions_e.swStartSketchPlane,
                    0.0, false, true);
            }
            else
            {
                feature = model.FeatureManager.FeatureExtrusion3(
                    true, false, false, (int)swEndConditions_e.swEndCondBlind, (int)swEndConditions_e.swEndCondBlind,
                    depthMeters, 0.0, false, false, false, false, 0.0, 0.0,
                    false, false, false, false, true, true, true,
                    (int)swStartConditions_e.swStartSketchPlane, 0.0, false);
            }
            if (feature == null)
            {
                throw new InvalidOperationException(featurePlan.id + " SolidWorks feature creation returned null.");
            }
            feature.Name = "AICAD_" + featurePlan.id + "_" + featurePlan.type.ToUpperInvariant();
            features.Add(featurePlan.id, feature);
            bool previousDialog = model.ShowFeatureErrorDialog;
            model.ShowFeatureErrorDialog = false;
            model.ForceRebuild3(false);
            model.ShowFeatureErrorDialog = previousDialog;
            report.feature_error_code = feature.GetErrorCode2(out bool warning);
            report.feature_warning = warning;
            CaptureFeatureTopology(model, featurePlan, feature, report.native_topology);
            RefreshNativeTopology(model, report.native_topology);

            if (!string.IsNullOrEmpty(report.persistent_reference_base64))
            {
                byte[] reference = Convert.FromBase64String(report.persistent_reference_base64);
                object resolvedAfter = model.Extension.GetObjectByPersistReference3(reference, out int persistStatusAfter);
                report.persistent_reference_status = persistStatusAfter;
                report.persistent_reference_resolved = resolvedAfter != null && persistStatusAfter == 0;
                ReleaseCom(resolvedAfter);
            }
            report.after = CaptureSnapshot(model);
            report.actual_volume_delta_mm3 = report.after.volume_mm3 - report.before.volume_mm3;
            ValidateAfter(featurePlan, report, plan.tolerance_mm);
            report.passed = report.checks.All(item => item.StartsWith("PASS:", StringComparison.Ordinal));
            return report;
        }

        private static void ValidateExpectedBefore(FeaturePlan plan, ModelSnapshot snapshot, double tolerance, ICollection<string> checks)
        {
            double allowed = VolumeTolerance(plan.expected.volume_before_mm3, tolerance);
            if (Math.Abs(snapshot.volume_mm3 - plan.expected.volume_before_mm3) <= allowed)
                checks.Add("PASS:volume_before");
            else
                checks.Add("FAIL:volume_before expected=" + plan.expected.volume_before_mm3.ToString("R", CultureInfo.InvariantCulture) + " actual=" + snapshot.volume_mm3.ToString("R", CultureInfo.InvariantCulture));
        }

        private static void ValidateAfter(FeaturePlan plan, FeatureReport report, double tolerance)
        {
            if (report.feature_error_code == 0) report.checks.Add("PASS:feature_error_code");
            else report.checks.Add("FAIL:feature_error_code=" + report.feature_error_code);
            if (report.sketch_constraint_status == (int)swConstrainedStatus_e.swFullyConstrained) report.checks.Add("PASS:sketch_fully_constrained");
            else report.checks.Add("FAIL:sketch_constraint_status=" + report.sketch_constraint_status);
            if (report.after.body_fault_count == 0) report.checks.Add("PASS:body_valid");
            else report.checks.Add("FAIL:body_fault_count=" + report.after.body_fault_count);
            if (string.IsNullOrEmpty(plan.support_feature))
                report.checks.Add("PASS:support_plane_not_applicable");
            else if (report.support_face_selection_method == "named_feature_exact_z" &&
                     report.selected_support_plane_z_mm.HasValue &&
                     Math.Abs(report.selected_support_plane_z_mm.Value - plan.support_top_z_mm) <= Math.Max(0.0001, tolerance))
                report.checks.Add("PASS:support_plane_feature_and_z");
            else
                report.checks.Add("FAIL:support_plane_feature_and_z expected_feature=" + plan.support_feature +
                    " expected_z_mm=" + plan.support_top_z_mm.ToString("R", CultureInfo.InvariantCulture));
            if (report.after.solid_body_count == plan.expected.solid_body_count) report.checks.Add("PASS:solid_body_count");
            else report.checks.Add("FAIL:solid_body_count expected=" + plan.expected.solid_body_count + " actual=" + report.after.solid_body_count);
            double allowedVolume = VolumeTolerance(plan.expected.volume_after_mm3, tolerance);
            if (Math.Abs(report.after.volume_mm3 - plan.expected.volume_after_mm3) <= allowedVolume) report.checks.Add("PASS:volume_after");
            else report.checks.Add("FAIL:volume_after expected=" + plan.expected.volume_after_mm3.ToString("R", CultureInfo.InvariantCulture) + " actual=" + report.after.volume_mm3.ToString("R", CultureInfo.InvariantCulture));
            double allowedDelta = VolumeTolerance(Math.Abs(plan.expected.volume_delta_mm3), tolerance);
            if (Math.Abs(report.actual_volume_delta_mm3 - plan.expected.volume_delta_mm3) <= allowedDelta) report.checks.Add("PASS:volume_delta");
            else report.checks.Add("FAIL:volume_delta expected=" + plan.expected.volume_delta_mm3.ToString("R", CultureInfo.InvariantCulture) + " actual=" + report.actual_volume_delta_mm3.ToString("R", CultureInfo.InvariantCulture));
            if (report.after.bbox_mm != null && plan.expected.bbox_mm != null && report.after.bbox_mm.Length == 6 && plan.expected.bbox_mm.Length == 6 && Enumerable.Range(0, 6).All(index => Math.Abs(report.after.bbox_mm[index] - plan.expected.bbox_mm[index]) <= Math.Max(0.01, tolerance * 10)))
                report.checks.Add("PASS:bbox");
            else
                report.checks.Add("FAIL:bbox");
            if (string.IsNullOrEmpty(report.persistent_reference_base64) || report.persistent_reference_resolved)
                report.checks.Add("PASS:persistent_reference");
            else
                report.checks.Add("FAIL:persistent_reference");
            int requiredNative = report.native_topology.Count(item => item.required);
            int unresolvedRequiredNative = report.native_topology.Count(item => item.required && !item.persistent_reference_resolved);
            if (requiredNative > 0 && unresolvedRequiredNative == 0)
                report.checks.Add("PASS:native_topology_required_refs");
            else
                report.checks.Add("FAIL:native_topology_required_refs required=" + requiredNative + " unresolved=" + unresolvedRequiredNative);
        }

        private static double VolumeTolerance(double expected, double linearTolerance)
        {
            return Math.Max(0.5, Math.Max(Math.Abs(expected) * 1e-6, linearTolerance * linearTolerance * linearTolerance * 10.0));
        }

        private static Feature FirstReferencePlane(ModelDoc2 model)
        {
            Feature feature = (Feature)model.FirstFeature();
            while (feature != null)
            {
                if (string.Equals(feature.GetTypeName2(), "RefPlane", StringComparison.Ordinal))
                    return feature;
                feature = (Feature)feature.GetNextFeature();
            }
            return null;
        }

        private static Face2 SelectPlanarSupportFace(
            ModelDoc2 model,
            FeaturePlan feature,
            IDictionary<string, Feature> features,
            out double actualPlaneZMm)
        {
            actualPlaneZMm = double.NaN;
            if (string.IsNullOrEmpty(feature.support_feature) || !features.TryGetValue(feature.support_feature, out Feature supportFeature))
                throw new InvalidOperationException(feature.id + " could not resolve its declared support feature " + feature.support_feature + ".");
            object rawFaces = supportFeature.GetFaces();
            Array faces = rawFaces as Array;
            if (faces == null || faces.Length == 0)
                throw new InvalidOperationException(feature.id + " declared support feature has no current faces: " + feature.support_feature + ".");

            double targetZMeters = feature.support_top_z_mm / MillimetersPerMeter;
            const double planeToleranceMeters = 1e-7;
            Face2 selectedFace = null;
            var horizontalPlaneLevelsMm = new List<string>();
            foreach (object value in faces)
            {
                Face2 candidate = value as Face2;
                if (candidate == null) continue;
                Surface surface = candidate.GetSurface() as Surface;
                double[] box = candidate.GetBox() as double[];
                bool planar = surface != null && surface.IsPlane();
                bool horizontal = planar && box != null && box.Length >= 6 && Math.Abs(box[5] - box[2]) <= planeToleranceMeters;
                if (horizontal)
                    horizontalPlaneLevelsMm.Add((box[2] * MillimetersPerMeter).ToString("R", CultureInfo.InvariantCulture));
                bool exactZ = horizontal && Math.Abs(box[2] - targetZMeters) <= planeToleranceMeters && Math.Abs(box[5] - targetZMeters) <= planeToleranceMeters;
                ReleaseCom(surface);
                if (exactZ)
                {
                    selectedFace = candidate;
                    actualPlaneZMm = (box[2] + box[5]) * MillimetersPerMeter / 2.0;
                    break;
                }
                ReleaseCom(candidate);
            }
            if (selectedFace == null)
                throw new InvalidOperationException(
                    feature.id + " could not resolve an exact-Z planar face on support feature " + feature.support_feature +
                    "; expected_z_mm=" + feature.support_top_z_mm.ToString("R", CultureInfo.InvariantCulture) +
                    "; available_horizontal_z_mm=[" + string.Join(",", horizontalPlaneLevelsMm) + "].");

            model.ClearSelection2(true);
            Entity entity = selectedFace as Entity;
            if (entity == null || !entity.Select4(false, null))
                throw new InvalidOperationException(feature.id + " could not select the exact-Z face of support feature " + feature.support_feature + ".");
            return selectedFace;
        }
        private static List<SketchSegment> CreateProfile(SldWorks app, Sketch sketch, SketchManager manager, ProfilePlan profile, double supportTopZmm)
        {
            var segments = new List<SketchSegment>();
            double[] center = ModelPointToSketch(app, sketch, profile.center_x_mm, profile.center_y_mm, supportTopZmm);
            if (profile.kind == "center_rectangle")
            {
                double halfWidthMm = profile.width_mm.Value / 2.0;
                double halfHeightMm = profile.height_mm.Value / 2.0;
                double[] corner = ModelPointToSketch(
                    app, sketch, profile.center_x_mm + halfWidthMm, profile.center_y_mm + halfHeightMm, supportTopZmm);
                double[] opposite = ModelPointToSketch(
                    app, sketch, profile.center_x_mm - halfWidthMm, profile.center_y_mm - halfHeightMm, supportTopZmm);
                var points = new[] {
                    new[] { opposite[0], opposite[1] },
                    new[] { corner[0], opposite[1] },
                    new[] { corner[0], corner[1] },
                    new[] { opposite[0], corner[1] },
                };
                for (int index = 0; index < 4; index++)
                {
                    double[] start = points[index];
                    double[] end = points[(index + 1) % 4];
                    SketchSegment segment = manager.CreateLine(start[0], start[1], 0.0, end[0], end[1], 0.0);
                    if (segment == null) throw new InvalidOperationException("SolidWorks failed to create rectangle edge " + (index + 1) + ".");
                    segments.Add(segment);
                }
                return segments;
            }
            if (profile.circles == null || profile.circles.Count == 0)
                throw new InvalidOperationException("Circle profile contains no primitives.");
            foreach (CirclePlan circle in profile.circles)
            {
                double[] circleCenter = ModelPointToSketch(app, sketch, circle.x_mm, circle.y_mm, supportTopZmm);
                SketchSegment segment = manager.CreateCircleByRadius(circleCenter[0], circleCenter[1], 0.0, circle.radius_mm / MillimetersPerMeter);
                if (segment == null) throw new InvalidOperationException("SolidWorks failed to create circle profile.");
                segments.Add(segment);
            }
            return segments;
        }

        private static string SketchConstraintDiagnostics(Sketch sketch, IList<SketchSegment> segments)
        {
            string segmentStatuses = segments == null
                ? "null"
                : string.Join(",", segments.Select(segment => segment.Status.ToString(CultureInfo.InvariantCulture)));
            var pointStatuses = new List<string>();
            object rawPoints = sketch.GetSketchPoints2();
            Array points = rawPoints as Array;
            if (points != null)
            {
                foreach (object value in points)
                {
                    SketchPoint point = value as SketchPoint;
                    if (point != null)
                    {
                        pointStatuses.Add(point.Status.ToString(CultureInfo.InvariantCulture));
                        ReleaseCom(point);
                    }
                }
            }
            SketchRelationManager relationManager = sketch.RelationManager;
            int relationCount = relationManager == null
                ? -1
                : relationManager.GetRelationsCount((int)swSketchRelationFilterType_e.swAll);
            ReleaseCom(relationManager);
            return "segment_statuses=[" + segmentStatuses + "]; point_statuses=[" +
                string.Join(",", pointStatuses) + "]; relation_count=" + relationCount.ToString(CultureInfo.InvariantCulture);
        }
        private static double[] ModelPointToSketch(SldWorks app, Sketch sketch, double xMm, double yMm, double zMm)
        {
            MathUtility utility = null;
            MathTransform transform = null;
            MathPoint modelPoint = null;
            MathPoint sketchPoint = null;
            try
            {
                utility = (MathUtility)app.GetMathUtility();
                transform = sketch.ModelToSketchTransform;
                modelPoint = (MathPoint)utility.CreatePoint(new double[] {
                    xMm / MillimetersPerMeter, yMm / MillimetersPerMeter, zMm / MillimetersPerMeter
                });
                sketchPoint = (MathPoint)modelPoint.MultiplyTransform(transform);
                double[] coordinates = sketchPoint.ArrayData as double[];
                if (coordinates == null || coordinates.Length < 3)
                    throw new InvalidOperationException("SolidWorks returned an invalid model-to-sketch coordinate transform.");
                return coordinates;
            }
            finally
            {
                ReleaseCom(sketchPoint);
                ReleaseCom(modelPoint);
                ReleaseCom(transform);
                ReleaseCom(utility);
            }
        }

        private static void AddExplicitRectangleConstraints(
            SldWorks app,
            ModelDoc2 model,
            Sketch sketch,
            SketchPoint datumPoint,
            ProfilePlan profile,
            double supportTopZmm,
            IList<SketchSegment> segments,
            out int sizeDimensions,
            out int positionDimensions,
            out int positionRelations)
        {
            sizeDimensions = 0;
            positionDimensions = 0;
            positionRelations = 0;
            if (profile.kind != "center_rectangle") return;
            if (segments == null || segments.Count != 4)
                throw new InvalidOperationException("Rectangle profile must contain four ordered segments before explicit constraints.");
            SketchLine bottomLine = segments[0] as SketchLine;
            SketchLine rightLine = segments[1] as SketchLine;
            if (bottomLine == null || rightLine == null)
                throw new InvalidOperationException("Rectangle profile segments are not native SketchLine objects.");
            SketchPoint lowerLeft = bottomLine.GetStartPoint2() as SketchPoint;
            SketchPoint lowerRight = bottomLine.GetEndPoint2() as SketchPoint;
            SketchPoint upperRight = rightLine.GetEndPoint2() as SketchPoint;
            if (lowerLeft == null || lowerRight == null || upperRight == null)
                throw new InvalidOperationException("Rectangle profile corner points could not be resolved for explicit constraints.");

            double[] center = ModelPointToSketch(app, sketch, profile.center_x_mm, profile.center_y_mm, supportTopZmm);
            double[] lowerLeftCoordinate = ModelPointToSketch(
                app, sketch,
                profile.center_x_mm - profile.width_mm.Value / 2.0,
                profile.center_y_mm - profile.height_mm.Value / 2.0,
                supportTopZmm);
            double[] lowerRightCoordinate = ModelPointToSketch(
                app, sketch,
                profile.center_x_mm + profile.width_mm.Value / 2.0,
                profile.center_y_mm - profile.height_mm.Value / 2.0,
                supportTopZmm);
            double[] upperRightCoordinate = ModelPointToSketch(
                app, sketch,
                profile.center_x_mm + profile.width_mm.Value / 2.0,
                profile.center_y_mm + profile.height_mm.Value / 2.0,
                supportTopZmm);
            double offset = Math.Max(Math.Max(profile.width_mm.Value, profile.height_mm.Value) * 0.2 / MillimetersPerMeter, 0.002);
            double zeroTolerance = 1e-10;
            int preference = (int)swUserPreferenceToggle_e.swInputDimValOnCreate;
            bool originalInputDimensionValue = app.GetUserPreferenceToggle(preference);
            try
            {
                app.SetUserPreferenceToggle(preference, false);

                SelectPointPair(model, lowerLeft, lowerRight, "rectangle width dimension");
                object widthDimension = model.AddHorizontalDimension2(
                    center[0], lowerLeftCoordinate[1] - offset, 0.0);
                if (widthDimension == null)
                    throw new InvalidOperationException("SolidWorks could not create the explicit rectangle width dimension.");
                ReleaseCom(widthDimension);
                sizeDimensions++;

                SelectPointPair(model, lowerRight, upperRight, "rectangle height dimension");
                object heightDimension = model.AddVerticalDimension2(
                    lowerRightCoordinate[0] + offset, center[1], 0.0);
                if (heightDimension == null)
                    throw new InvalidOperationException("SolidWorks could not create the explicit rectangle height dimension.");
                ReleaseCom(heightDimension);
                sizeDimensions++;

                if (Math.Abs(lowerLeftCoordinate[0]) <= zeroTolerance)
                {
                    SelectPointPair(model, datumPoint, lowerLeft, "rectangle lower-left vertical relation");
                    model.SketchAddConstraints("sgVERTICALPOINTS2D");
                    positionRelations++;
                }
                else
                {
                    SelectPointPair(model, datumPoint, lowerLeft, "rectangle lower-left X dimension");
                    object xDimension = model.AddHorizontalDimension2(
                        lowerLeftCoordinate[0] * 0.5,
                        lowerLeftCoordinate[1] - offset,
                        0.0);
                    if (xDimension == null)
                        throw new InvalidOperationException("SolidWorks could not create the explicit rectangle X-position dimension.");
                    ReleaseCom(xDimension);
                    positionDimensions++;
                }

                if (Math.Abs(lowerLeftCoordinate[1]) <= zeroTolerance)
                {
                    SelectPointPair(model, datumPoint, lowerLeft, "rectangle lower-left horizontal relation");
                    model.SketchAddConstraints("sgHORIZONTALPOINTS2D");
                    positionRelations++;
                }
                else
                {
                    SelectPointPair(model, datumPoint, lowerLeft, "rectangle lower-left Y dimension");
                    object yDimension = model.AddVerticalDimension2(
                        lowerLeftCoordinate[0] - offset,
                        lowerLeftCoordinate[1] * 0.5,
                        0.0);
                    if (yDimension == null)
                        throw new InvalidOperationException("SolidWorks could not create the explicit rectangle Y-position dimension.");
                    ReleaseCom(yDimension);
                    positionDimensions++;
                }
                model.ClearSelection2(true);
            }
            finally
            {
                app.SetUserPreferenceToggle(preference, originalInputDimensionValue);
            }
        }

        private static void AddExplicitCircleConstraints(
            SldWorks app,
            ModelDoc2 model,
            Sketch sketch,
            SketchPoint datumPoint,
            ProfilePlan profile,
            double supportTopZmm,
            IList<SketchSegment> segments,
            out int radiusDimensions,
            out int centerDimensions,
            out int centerRelations)
        {
            radiusDimensions = 0;
            centerDimensions = 0;
            centerRelations = 0;
            if (profile.circles == null || profile.circles.Count == 0) return;
            if (segments == null || segments.Count != profile.circles.Count)
                throw new InvalidOperationException("Circle profile segment count does not match its frozen primitives.");
            int preference = (int)swUserPreferenceToggle_e.swInputDimValOnCreate;
            bool originalInputDimensionValue = app.GetUserPreferenceToggle(preference);
            try
            {
                // Headless execution must never open the interactive Modify Dimension dialog.
                app.SetUserPreferenceToggle(preference, false);
                for (int index = 0; index < profile.circles.Count; index++)
                {
                    CirclePlan circle = profile.circles[index];
                    SketchArc arc = segments[index] as SketchArc;
                    SketchPoint centerPoint = arc == null ? null : arc.GetCenterPoint2() as SketchPoint;
                    if (centerPoint == null)
                        throw new InvalidOperationException("SolidWorks could not resolve a circle center point for explicit constraints.");
                    double[] circleCenter = ModelPointToSketch(app, sketch, circle.x_mm, circle.y_mm, supportTopZmm);
                    double zeroTolerance = 1e-10;
                    double dimensionOffset = Math.Max(circle.radius_mm * 1.5 / MillimetersPerMeter, 0.002);

                    if (Math.Abs(circleCenter[0]) <= zeroTolerance && Math.Abs(circleCenter[1]) <= zeroTolerance)
                    {
                        SelectPointPair(model, datumPoint, centerPoint, "coincident circle-center relation");
                        model.SketchAddConstraints("sgCOINCIDENT");
                        centerRelations++;
                    }
                    else
                    {
                        if (Math.Abs(circleCenter[0]) <= zeroTolerance)
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "vertical circle-center relation");
                            model.SketchAddConstraints("sgVERTICALPOINTS2D");
                            centerRelations++;
                        }
                        else
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "horizontal circle-center dimension");
                            object horizontalDimension = model.AddHorizontalDimension2(
                                circleCenter[0] * 0.5,
                                circleCenter[1] - dimensionOffset,
                                0.0);
                            if (horizontalDimension == null)
                                throw new InvalidOperationException("SolidWorks could not create an explicit circle-center X dimension.");
                            ReleaseCom(horizontalDimension);
                            centerDimensions++;
                        }

                        if (Math.Abs(circleCenter[1]) <= zeroTolerance)
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "horizontal circle-center relation");
                            model.SketchAddConstraints("sgHORIZONTALPOINTS2D");
                            centerRelations++;
                        }
                        else
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "vertical circle-center dimension");
                            object verticalDimension = model.AddVerticalDimension2(
                                circleCenter[0] + dimensionOffset,
                                circleCenter[1] * 0.5,
                                0.0);
                            if (verticalDimension == null)
                                throw new InvalidOperationException("SolidWorks could not create an explicit circle-center Y dimension.");
                            ReleaseCom(verticalDimension);
                            centerDimensions++;
                        }
                    }

                    model.ClearSelection2(true);
                    if (!segments[index].Select4(false, null))
                        throw new InvalidOperationException("SolidWorks could not select a circle for its explicit radial dimension.");
                    double[] dimensionText = ModelPointToSketch(
                        app, sketch,
                        circle.x_mm + circle.radius_mm * 1.5,
                        circle.y_mm + circle.radius_mm * 0.5,
                        supportTopZmm);
                    object dimension = model.AddRadialDimension2(dimensionText[0], dimensionText[1], 0.0);
                    if (dimension == null)
                        throw new InvalidOperationException("SolidWorks could not create an explicit circle radius dimension.");
                    ReleaseCom(dimension);
                    model.ClearSelection2(true);
                    radiusDimensions++;
                }
            }
            finally
            {
                app.SetUserPreferenceToggle(preference, originalInputDimensionValue);
            }
        }

        private static void SelectPointPair(ModelDoc2 model, SketchPoint first, SketchPoint second, string purpose)
        {
            model.ClearSelection2(true);
            if (!first.Select4(false, null) || !second.Select4(true, null))
                throw new InvalidOperationException("SolidWorks could not select points for " + purpose + ".");
        }
        private static NativeTopologyReference CapturePersistentReference(
            ModelDoc2 model, object nativeObject, string referenceKey, string semanticGeometryType,
            string nativeObjectType, string classification, bool required, double[] signatureMm)
        {
            if (nativeObject == null) return null;
            byte[] bytes = model.Extension.GetPersistReference3(nativeObject) as byte[];
            if (bytes == null || bytes.Length == 0)
            {
                if (required) throw new InvalidOperationException("Could not create required persistent reference " + referenceKey + ".");
                return null;
            }
            object resolved = model.Extension.GetObjectByPersistReference3(bytes, out int status);
            bool isResolved = resolved != null && status == (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Ok;
            // Do not FinalReleaseComObject here: SolidWorks can return the same RCW as
            // nativeObject, and disconnecting it would invalidate the caller's face/edge.
            if (required && !isResolved)
                throw new InvalidOperationException("Required persistent reference did not resolve: " + referenceKey + "; status=" + status);
            return new NativeTopologyReference
            {
                reference_key = referenceKey,
                semantic_geometry_type = semanticGeometryType,
                native_object_type = nativeObjectType,
                classification = classification,
                persistent_reference_base64 = Convert.ToBase64String(bytes),
                persistent_reference_status = status,
                persistent_reference_resolved = isResolved,
                required = required,
                signature_mm = signatureMm,
            };
        }

        private static void AddNativeTopology(ICollection<NativeTopologyReference> target, NativeTopologyReference item)
        {
            if (item == null) return;
            NativeTopologyReference existing = target.FirstOrDefault(value => value.reference_key == item.reference_key);
            if (existing == null)
            {
                target.Add(item);
                return;
            }
            if (existing.persistent_reference_base64 != item.persistent_reference_base64)
                throw new InvalidOperationException("Native topology classification is ambiguous for " + item.reference_key + ".");
        }

        private static void CaptureSketchTopology(
            ModelDoc2 model, FeaturePlan plan, IList<SketchSegment> segments, ICollection<NativeTopologyReference> target)
        {
            if (segments == null) throw new InvalidOperationException(plan.id + " has no sketch segments for native topology capture.");
            if (plan.profile.kind == "center_rectangle")
            {
                if (segments.Count != 4) throw new InvalidOperationException(plan.id + " rectangle must contain exactly four ordered edges.");
                double left = plan.profile.center_x_mm - plan.profile.width_mm.Value / 2.0;
                double right = plan.profile.center_x_mm + plan.profile.width_mm.Value / 2.0;
                double bottom = plan.profile.center_y_mm - plan.profile.height_mm.Value / 2.0;
                double top = plan.profile.center_y_mm + plan.profile.height_mm.Value / 2.0;
                double[][] signatures = {
                    new[] { left, bottom, right, bottom, plan.support_top_z_mm },
                    new[] { right, bottom, right, top, plan.support_top_z_mm },
                    new[] { right, top, left, top, plan.support_top_z_mm },
                    new[] { left, top, left, bottom, plan.support_top_z_mm },
                };
                for (int index = 0; index < 4; index++)
                    AddNativeTopology(target, CapturePersistentReference(
                        model, segments[index], plan.id + "|profile.edge." + (index + 1), "line", "SketchSegment",
                        "ordered_rectangle_profile_edge", true, signatures[index]));
                return;
            }
            if (plan.profile.circles == null || segments.Count != plan.profile.circles.Count)
                throw new InvalidOperationException(plan.id + " circle segment count does not match its semantic profile.");
            for (int index = 0; index < segments.Count; index++)
            {
                CirclePlan circle = plan.profile.circles[index];
                AddNativeTopology(target, CapturePersistentReference(
                    model, segments[index], plan.id + "|profile.circle." + (index + 1), "circle", "SketchSegment",
                    "ordered_profile_circle", true,
                    new[] { circle.x_mm, circle.y_mm, plan.support_top_z_mm, circle.radius_mm }));
            }
        }

        private static void RefreshNativeTopology(ModelDoc2 model, IEnumerable<NativeTopologyReference> references)
        {
            foreach (NativeTopologyReference item in references)
            {
                byte[] bytes = Convert.FromBase64String(item.persistent_reference_base64);
                object resolved = model.Extension.GetObjectByPersistReference3(bytes, out int status);
                item.persistent_reference_status = status;
                item.persistent_reference_resolved = resolved != null && status == (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Ok;
                ReleaseCom(resolved);
                if (item.required && !item.persistent_reference_resolved)
                    throw new InvalidOperationException("Required native topology reference became unresolved: " + item.reference_key + ".");
            }
        }

        private static bool Near(double first, double second, double toleranceMm = 0.001)
        {
            return Math.Abs(first - second) <= toleranceMm;
        }

        private static double[] BoxMm(Face2 face)
        {
            double[] box = face == null ? null : face.GetBox() as double[];
            return box == null ? null : box.Select(value => value * MillimetersPerMeter).ToArray();
        }

        private static void CaptureFeatureTopology(
            ModelDoc2 model, FeaturePlan plan, Feature feature, ICollection<NativeTopologyReference> target)
        {
            Array faces = feature.GetFaces() as Array;
            if (faces == null) return;
            var faceValues = new List<Face2>();
            foreach (object raw in faces)
            {
                Face2 face = raw as Face2;
                if (face != null) faceValues.Add(face);
            }
            if (plan.profile.kind == "center_rectangle")
                CaptureRectangleFeatureTopology(model, plan, faceValues, target);
            else
                CaptureCircularFeatureTopology(model, plan, faceValues, target);
        }

        private static void CaptureRectangleFeatureTopology(
            ModelDoc2 model, FeaturePlan plan, IEnumerable<Face2> faces, ICollection<NativeTopologyReference> target)
        {
            double left = plan.profile.center_x_mm - plan.profile.width_mm.Value / 2.0;
            double right = plan.profile.center_x_mm + plan.profile.width_mm.Value / 2.0;
            double bottom = plan.profile.center_y_mm - plan.profile.height_mm.Value / 2.0;
            double top = plan.profile.center_y_mm + plan.profile.height_mm.Value / 2.0;
            double oppositeZ = plan.type == "cut_extrude"
                ? (plan.end_condition == "through_all" ? 0.0 : plan.support_top_z_mm - plan.depth_mm)
                : plan.resulting_top_z_mm;
            foreach (Face2 face in faces)
            {
                Surface surface = face.GetSurface() as Surface;
                double[] box = BoxMm(face);
                bool planar = surface != null && surface.IsPlane();
                ReleaseCom(surface);
                if (!planar || box == null || box.Length < 6) continue;
                string key = null;
                string classification = null;
                if (Near(box[2], box[5]) && Near(box[2], oppositeZ))
                {
                    key = plan.id + "|feature.face.opposite";
                    classification = "opposite_planar_face";
                }
                else if (Near(box[1], box[4]) && Near(box[1], bottom))
                {
                    key = plan.id + "|feature.face.side.1";
                    classification = "rectangle_side_bottom";
                }
                else if (Near(box[0], box[3]) && Near(box[0], right))
                {
                    key = plan.id + "|feature.face.side.2";
                    classification = "rectangle_side_right";
                }
                else if (Near(box[1], box[4]) && Near(box[1], top))
                {
                    key = plan.id + "|feature.face.side.3";
                    classification = "rectangle_side_top";
                }
                else if (Near(box[0], box[3]) && Near(box[0], left))
                {
                    key = plan.id + "|feature.face.side.4";
                    classification = "rectangle_side_left";
                }
                if (key != null)
                    AddNativeTopology(target, CapturePersistentReference(
                        model, face, key, "face", "Face2", classification, false, box));
            }
            CaptureRectangleEdges(model, plan, faces, target, left, bottom, right, top, oppositeZ);
        }

        private static void CaptureRectangleEdges(
            ModelDoc2 model, FeaturePlan plan, IEnumerable<Face2> faces, ICollection<NativeTopologyReference> target,
            double left, double bottom, double right, double top, double oppositeZ)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (Face2 face in faces)
            {
                Array edges = face.GetEdges() as Array;
                if (edges == null) continue;
                foreach (object raw in edges)
                {
                    Edge edge = raw as Edge;
                    if (edge == null) continue;
                    byte[] dedupeBytes = model.Extension.GetPersistReference3(edge) as byte[];
                    if (dedupeBytes == null || !seen.Add(Convert.ToBase64String(dedupeBytes))) continue;
                    Vertex start = edge.GetStartVertex() as Vertex;
                    Vertex end = edge.GetEndVertex() as Vertex;
                    double[] a = start == null ? null : start.GetPoint() as double[];
                    double[] b = end == null ? null : end.GetPoint() as double[];
                    ReleaseCom(start);
                    ReleaseCom(end);
                    if (a == null || b == null) continue;
                    double[] p = a.Concat(b).Select(value => value * MillimetersPerMeter).ToArray();
                    string key = null;
                    string classification = null;
                    bool sameZ = Near(p[2], p[5]);
                    if (sameZ && Near(p[2], oppositeZ))
                    {
                        key = RectangleBoundaryKey(plan.id + "|feature.edge.opposite.", p, left, bottom, right, top);
                        classification = "opposite_rectangle_edge";
                    }
                    else if (Near(p[0], p[3]) && Near(p[1], p[4]) && !sameZ)
                    {
                        key = RectangleCornerKey(plan.id + "|feature.edge.vertical.", p[0], p[1], left, bottom, right, top);
                        classification = "vertical_rectangle_edge";
                    }
                    if (key != null)
                        AddNativeTopology(target, CapturePersistentReference(
                            model, edge, key, "line", "Edge", classification, false, p));
                }
            }
        }

        private static string RectangleBoundaryKey(string prefix, double[] p, double left, double bottom, double right, double top)
        {
            if (Near(p[1], bottom) && Near(p[4], bottom)) return prefix + "1";
            if (Near(p[0], right) && Near(p[3], right)) return prefix + "2";
            if (Near(p[1], top) && Near(p[4], top)) return prefix + "3";
            if (Near(p[0], left) && Near(p[3], left)) return prefix + "4";
            return null;
        }

        private static string RectangleCornerKey(string prefix, double x, double y, double left, double bottom, double right, double top)
        {
            if (Near(x, left) && Near(y, bottom)) return prefix + "1";
            if (Near(x, right) && Near(y, bottom)) return prefix + "2";
            if (Near(x, right) && Near(y, top)) return prefix + "3";
            if (Near(x, left) && Near(y, top)) return prefix + "4";
            return null;
        }

        private static void CaptureCircularFeatureTopology(
            ModelDoc2 model, FeaturePlan plan, IEnumerable<Face2> faces, ICollection<NativeTopologyReference> target)
        {
            if (plan.profile.circles == null) return;
            double oppositeZ = plan.type == "cut_extrude"
                ? (plan.end_condition == "through_all" ? 0.0 : plan.support_top_z_mm - plan.depth_mm)
                : plan.resulting_top_z_mm;
            var seenEdges = new HashSet<string>(StringComparer.Ordinal);
            foreach (Face2 face in faces)
            {
                Surface surface = face.GetSurface() as Surface;
                double[] box = BoxMm(face);
                bool cylindrical = surface != null && surface.IsCylinder();
                bool planar = surface != null && surface.IsPlane();
                ReleaseCom(surface);
                if (box == null || box.Length < 6) continue;
                for (int index = 0; index < plan.profile.circles.Count; index++)
                {
                    CirclePlan circle = plan.profile.circles[index];
                    bool xyMatch = Near((box[0] + box[3]) / 2.0, circle.x_mm) &&
                        Near((box[1] + box[4]) / 2.0, circle.y_mm) &&
                        Near((box[3] - box[0]) / 2.0, circle.radius_mm) &&
                        Near((box[4] - box[1]) / 2.0, circle.radius_mm);
                    if (!xyMatch) continue;
                    if (cylindrical)
                        AddNativeTopology(target, CapturePersistentReference(
                            model, face, plan.id + "|feature.face.cylindrical." + (index + 1), "face", "Face2",
                            "cylindrical_face", false, box));
                    else if (planar && Near(box[2], box[5]) && Near(box[2], oppositeZ))
                        AddNativeTopology(target, CapturePersistentReference(
                            model, face, plan.id + "|feature.face.opposite." + (index + 1), "face", "Face2",
                            "opposite_circular_face", false, box));
                }
                Array edges = face.GetEdges() as Array;
                if (edges == null) continue;
                foreach (object raw in edges)
                {
                    Edge edge = raw as Edge;
                    if (edge == null) continue;
                    byte[] dedupeBytes = model.Extension.GetPersistReference3(edge) as byte[];
                    if (dedupeBytes == null || !seenEdges.Add(Convert.ToBase64String(dedupeBytes))) continue;
                    Curve curve = edge.GetCurve() as Curve;
                    if (curve == null || !curve.IsCircle()) { ReleaseCom(curve); continue; }
                    double[] parameters = curve.CircleParams as double[];
                    ReleaseCom(curve);
                    if (parameters == null || parameters.Length < 7) continue;
                    double centerX = parameters[0] * MillimetersPerMeter;
                    double centerY = parameters[1] * MillimetersPerMeter;
                    double centerZ = parameters[2] * MillimetersPerMeter;
                    double radius = parameters[6] * MillimetersPerMeter;
                    for (int index = 0; index < plan.profile.circles.Count; index++)
                    {
                        CirclePlan circle = plan.profile.circles[index];
                        if (Near(centerX, circle.x_mm) && Near(centerY, circle.y_mm) &&
                            Near(centerZ, oppositeZ) && Near(radius, circle.radius_mm))
                            AddNativeTopology(target, CapturePersistentReference(
                                model, edge, plan.id + "|feature.circle.opposite." + (index + 1), "circle", "Edge",
                                "opposite_circular_edge", false, new[] { centerX, centerY, centerZ, radius }));
                    }
                }
            }
        }

        private static void PersistNativeTopologyCatalog(ModelDoc2 model, HostReport report)
        {
            List<NativeTopologyReference> catalog = report.features.SelectMany(item => item.native_topology).ToList();
            RefreshNativeTopology(model, catalog);
            if (catalog.Select(item => item.reference_key).Distinct(StringComparer.Ordinal).Count() != catalog.Count)
                throw new InvalidOperationException("Native topology catalog contains duplicate semantic reference keys.");
            CustomPropertyManager properties = model.Extension.CustomPropertyManager[""];
            if (properties == null) throw new InvalidOperationException("SolidWorks document custom-property manager is unavailable.");
            int ordinal = 0;
            foreach (NativeTopologyReference item in catalog.Where(value => value.persistent_reference_resolved))
            {
                ordinal++;
                string name = "AICAD_REF_" + ordinal.ToString("D4", CultureInfo.InvariantCulture);
                string value = string.Join("\t", new[] {
                    item.reference_key, item.semantic_geometry_type, item.native_object_type,
                    item.classification ?? "", item.required ? "1" : "0", item.persistent_reference_base64
                });
                properties.Add3(name, (int)swCustomInfoType_e.swCustomInfoText, value,
                    (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue);
                item.custom_property_name = name;
            }
            properties.Add3("AICAD_SOURCE_SHA256", (int)swCustomInfoType_e.swCustomInfoText,
                report.source_sha256 ?? "", (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue);
            properties.Add3("AICAD_REF_COUNT", (int)swCustomInfoType_e.swCustomInfoText,
                ordinal.ToString(CultureInfo.InvariantCulture), (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue);
            report.native_topology_reference_count = catalog.Count;
            report.required_native_topology_reference_count = catalog.Count(item => item.required);
            report.unresolved_required_native_topology_reference_count = catalog.Count(item => item.required && !item.persistent_reference_resolved);
            if (report.required_native_topology_reference_count == 0 || report.unresolved_required_native_topology_reference_count != 0)
                throw new InvalidOperationException("Native topology catalog does not contain a complete set of resolvable required references.");
        }

        private static void ReadAndResolveNativeTopologyCatalog(ModelDoc2 model, ReopenReport report)
        {
            CustomPropertyManager properties = model.Extension.CustomPropertyManager[""];
            if (properties == null) throw new InvalidOperationException("SolidWorks document custom-property manager is unavailable after reopen.");
            Array names = properties.GetNames() as Array;
            if (names != null)
            {
                foreach (object rawName in names)
                {
                    string name = rawName as string;
                    if (string.IsNullOrEmpty(name) || name.Length != 14 ||
                        !name.StartsWith("AICAD_REF_", StringComparison.Ordinal) ||
                        !name.Substring(10).All(char.IsDigit)) continue;
                    properties.Get6(name, false, out string rawValue, out string resolvedValue, out bool wasResolved, out bool linked);
                    string value = string.IsNullOrEmpty(rawValue) ? resolvedValue : rawValue;
                    string[] fields = (value ?? "").Split('\t');
                    if (fields.Length != 6) throw new InvalidDataException("Malformed native topology custom property " + name + ".");
                    byte[] bytes = Convert.FromBase64String(fields[5]);
                    object resolved = model.Extension.GetObjectByPersistReference3(bytes, out int status);
                    bool isResolved = resolved != null && status == (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Ok;
                    ReleaseCom(resolved);
                    report.native_topology.Add(new NativeTopologyReference {
                        reference_key = fields[0], semantic_geometry_type = fields[1], native_object_type = fields[2],
                        classification = fields[3], required = fields[4] == "1",
                        persistent_reference_base64 = fields[5], persistent_reference_status = status,
                        persistent_reference_resolved = isResolved, custom_property_name = name,
                    });
                }
            }
            report.native_topology = report.native_topology.OrderBy(item => item.custom_property_name, StringComparer.Ordinal).ToList();
            if (report.native_topology.Select(item => item.reference_key).Distinct(StringComparer.Ordinal).Count() != report.native_topology.Count)
                throw new InvalidDataException("Reopened native topology catalog contains duplicate semantic reference keys.");
            report.native_topology_reference_count = report.native_topology.Count;
            report.required_native_topology_reference_count = report.native_topology.Count(item => item.required);
            report.unresolved_required_native_topology_reference_count = report.native_topology.Count(item => item.required && !item.persistent_reference_resolved);
        }

        private static ModelSnapshot CaptureSnapshot(ModelDoc2 model)
        {
            if (model == null) return new ModelSnapshot { bbox_mm = null };
            var part = (PartDoc)model;
            object rawBodies = part.GetBodies2((int)swBodyType_e.swSolidBody, false);
            object[] bodyObjects = rawBodies as object[];
            if (bodyObjects == null || bodyObjects.Length == 0)
                return new ModelSnapshot { solid_body_count = 0, body_fault_count = 0, volume_mm3 = 0.0, surface_area_mm2 = 0.0, bbox_mm = null };
            var bodies = bodyObjects.Cast<Body2>().ToArray();
            int faults = 0;
            foreach (Body2 body in bodies)
            {
                FaultEntity faultEntity = body.Check3;
                if (faultEntity != null)
                {
                    faults += faultEntity.Count;
                    ReleaseCom(faultEntity);
                }
            }
            MassProperty2 mass = (MassProperty2)model.Extension.CreateMassProperty2();
            if (mass == null) throw new InvalidOperationException("SolidWorks could not create mass properties.");
            mass.UseSystemUnits = true;
            var snapshot = new ModelSnapshot
            {
                solid_body_count = bodies.Length,
                body_fault_count = faults,
                volume_mm3 = mass.Volume * CubicMillimetersPerCubicMeter,
                surface_area_mm2 = mass.SurfaceArea * SquareMillimetersPerSquareMeter,
                bbox_mm = ExtremeBounds(bodies),
            };
            ReleaseCom(mass);
            return snapshot;
        }

        private static double[] ExtremeBounds(IEnumerable<Body2> bodies)
        {
            double minX = double.PositiveInfinity, minY = double.PositiveInfinity, minZ = double.PositiveInfinity;
            double maxX = double.NegativeInfinity, maxY = double.NegativeInfinity, maxZ = double.NegativeInfinity;
            foreach (Body2 body in bodies)
            {
                if (!body.GetExtremePoint(-1, 0, 0, out double x0, out _, out _)) throw new InvalidOperationException("Failed X-min extreme point.");
                if (!body.GetExtremePoint(1, 0, 0, out double x1, out _, out _)) throw new InvalidOperationException("Failed X-max extreme point.");
                if (!body.GetExtremePoint(0, -1, 0, out _, out double y0, out _)) throw new InvalidOperationException("Failed Y-min extreme point.");
                if (!body.GetExtremePoint(0, 1, 0, out _, out double y1, out _)) throw new InvalidOperationException("Failed Y-max extreme point.");
                if (!body.GetExtremePoint(0, 0, -1, out _, out _, out double z0)) throw new InvalidOperationException("Failed Z-min extreme point.");
                if (!body.GetExtremePoint(0, 0, 1, out _, out _, out double z1)) throw new InvalidOperationException("Failed Z-max extreme point.");
                minX = Math.Min(minX, x0); maxX = Math.Max(maxX, x1);
                minY = Math.Min(minY, y0); maxY = Math.Max(maxY, y1);
                minZ = Math.Min(minZ, z0); maxZ = Math.Max(maxZ, z1);
            }
            return new[] { minX, minY, minZ, maxX, maxY, maxZ }.Select(value => value * MillimetersPerMeter).ToArray();
        }

        private static void SaveOutputs(SldWorks app, ModelDoc2 model, HostPlan plan, HostReport report)
        {
            model.ClearSelection2(true);
            int partErrors = 0;
            int partWarnings = 0;
            bool partSaved = model.Extension.SaveAs3(plan.output_sldprt, (int)swSaveAsVersion_e.swSaveAsCurrentVersion, (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, null, ref partErrors, ref partWarnings);
            report.sldprt_save_errors = partErrors;
            report.sldprt_save_warnings = partWarnings;
            if (!partSaved || partErrors != 0) throw new InvalidOperationException("SLDPRT save failed, errors=" + partErrors + ", warnings=" + partWarnings);
            int activationErrors = 0;
            app.ActivateDoc3(model.GetTitle(), true, (int)swRebuildOnActivation_e.swDontRebuildActiveDoc, ref activationErrors);
            model.ClearSelection2(true);
            int stepErrors = 0;
            int stepWarnings = 0;
            bool stepSaved = model.Extension.SaveAs3(plan.output_step, (int)swSaveAsVersion_e.swSaveAsCurrentVersion, (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, null, ref stepErrors, ref stepWarnings);
            report.step_save_errors = stepErrors;
            report.step_save_warnings = stepWarnings;
            if (!stepSaved || stepErrors != 0) throw new InvalidOperationException("STEP save failed, errors=" + stepErrors + ", warnings=" + stepWarnings);
        }

        private static T ReadJson<T>(string path)
        {
            using (FileStream stream = File.OpenRead(path))
            {
                return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(stream);
            }
        }

        private static void WriteJson<T>(string path, T value)
        {
            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            using (FileStream stream = File.Create(temporary))
            {
                var serializer = new DataContractJsonSerializer(typeof(T), new DataContractJsonSerializerSettings { UseSimpleDictionaryFormat = true });
                using (var writer = JsonReaderWriterFactory.CreateJsonWriter(stream, Encoding.UTF8, false, true, "  "))
                {
                    serializer.WriteObject(writer, value);
                }
            }
            if (File.Exists(path)) File.Delete(path);
            File.Move(temporary, path);
        }

        private static void ReleaseCom(object value)
        {
            if (value != null && Marshal.IsComObject(value))
            {
                try { Marshal.FinalReleaseComObject(value); } catch { }
            }
        }
    }
}
